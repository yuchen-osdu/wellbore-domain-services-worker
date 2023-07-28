# Copyright 2023 Schlumberger
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import reduce
from itertools import combinations
from typing import List, Dict, Set, Callable
from asyncio import create_task, wait, gather

import pandas as pd
import numpy as np

from osdu.core.api.storage.blob_storage_base import BlobStorageBase

from .chunk_storage import upload_chunk, chunk_download_generator
from .chunk_meta import ChunkMeta
from .dataframe import split_into_chunks
from .constants import WRITE_MAX_COLUMNS_COUNT, WRITE_MAX_TOTAL_VALUES_COUNT
from .errors import BulkValidationError
from .validators import validate_df
from ..capture_timings import capture_timings
from ..logger import get_logger


def concat_vertical_dataframe(top_dataframe: pd.DataFrame, bottom_dataframe: pd.DataFrame) -> pd.DataFrame:
    return pd.concat((top_dataframe, bottom_dataframe), copy=False)


def combine_first_dataframe(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    return left.combine_first(right)


def auto_merge_dataframe(d1: pd.DataFrame, d2: pd.DataFrame):
    """apply a join outer if no common column, else combine first"""
    column_intersection = d1.columns.intersection(d2.columns)
    if column_intersection.empty:
        return d1.join(d2, how="outer")
    return d1.combine_first(d2)


async def merge_dataframes_from_storage(
    storage: BlobStorageBase,
    tenant,
    chunk_metas: List[ChunkMeta],
    merge_func: Callable[[pd.DataFrame, pd.DataFrame], pd.DataFrame],
    *,
    ensure_order: bool = False,
) -> pd.DataFrame:
    """
    screamingly download dataframes corresponding of meta requested and applies the merge function to produce one
    dataframe. If the merge function requires a specific order, it's the responsibility of caller to order
    as needed the `chunk_metas` list and set parameter `ensure_order` to `True`.
    :param storage:
    :param tenant:
    :param chunk_metas: list of meta of chunks to download and merge together
    :param merge_func: merge operation to apply, binary operation between two dataframe return one dataframe
    :param ensure_order: if set to `True`, chunks are merged in same order than the `chunk_metas`. Otherwise merge
        as soon as two dataframe are downloaded from storage
    :return: result dataframe from the merge of all chunks
    """
    merged_dataframe = pd.DataFrame()
    async for df in chunk_download_generator(
        storage, tenant, (m.get_filepath(ChunkMeta.FileType.CHUNK) for m in chunk_metas), ensure_order=ensure_order
    ):
        merged_dataframe = merge_func(merged_dataframe, df)

    return merged_dataframe


@capture_timings("resolve_single_conflict_group")
async def resolve_single_conflict_group(
    storage: BlobStorageBase,
    tenant,
    record_id: str,
    session_id: str,
    current_chunks: List[ChunkMeta],
    previous_chunks: List[ChunkMeta],
    *,
    reference_curve: str | None = None,
) -> List[ChunkMeta]:
    # if data may exceed memory capacity, caller may need to review their data and resend fresh
    # bulk using overwrite mode

    # as previous chunk do not have any conflict each other, there's merge to perform, only concat by row or column
    previous_by_hashes: Dict[str, List[ChunkMeta]] = {}
    for c in previous_chunks:
        previous_by_hashes.setdefault(c.column_hash, list()).append(c)

    # need to order by index for the vertical concat
    previous_by_hashes = {h: sorted(metas, key=lambda m: m.index.start) for h, metas in previous_by_hashes.items()}

    # fire tasks for fetch/concat similar shaped previous chunks
    previous_tasks = {
        h: create_task(
            merge_dataframes_from_storage(storage, tenant, metas, concat_vertical_dataframe, ensure_order=True)
        )
        for h, metas in previous_by_hashes.items()
    }

    try:
        merged_current = await merge_dataframes_from_storage(storage, tenant, current_chunks, auto_merge_dataframe)

        if previous_tasks:
            await wait(previous_tasks.values())

            # TODO can be optimized
            previous_df = reduce(combine_first_dataframe, (t.result() for t in previous_tasks.values()))
            previous_tasks.clear()
        else:
            previous_df = pd.DataFrame()
    except Exception:
        for t in previous_tasks.values():
            t.cancel()
        raise

    # TODO must keep NaN values from current data, current should always overwrite
    final_df = merged_current.combine_first(previous_df)
    validate_df(final_df, reference_curve)

    chunks = split_into_chunks(
        final_df, max_values_per_chunk=WRITE_MAX_TOTAL_VALUES_COUNT, max_columns_per_chunk=WRITE_MAX_COLUMNS_COUNT
    )

    resolved_chunk_meta = await gather(
        *[
            upload_chunk(storage, tenant, ch, None, record_id, session_id, reference_curve=reference_curve)
            for ch in chunks
        ]
    )
    return list(resolved_chunk_meta)


@capture_timings("resolve_conflicts")
async def resolve_conflicts(
    storage: BlobStorageBase,
    tenant,
    record_id: str,
    session_id: str,
    session_chunk_metas: List[ChunkMeta],
    previous_chunk_metas: List[ChunkMeta] | None,
    *,
    reference_curve: str | None = None,
) -> List[ChunkMeta]:
    """
    check if there's any conflicts within current session and optionally previous bulk in case of session mode update
    """

    # let's figure out if there's any conflicts
    chunk_metas = session_chunk_metas
    if previous_chunk_metas:
        for m in previous_chunk_metas:
            m.order = -1  # set negative order to previous chunks, so will be overwritten by the current ones
        chunk_metas.extend(previous_chunk_metas)
    conflict_groups = find_conflicts(chunk_metas)
    if not conflict_groups:
        return chunk_metas

    get_logger().info(f"resolving {len(conflict_groups)} group(s) in conflict")
    chunk_metas_without_conflict = [m for m in chunk_metas if not m.in_conflict]
    for conflict in conflict_groups:
        # let's resolve conflict sequentially to not overwhelm service
        chunk_metas_without_conflict.extend(
            await resolve_single_conflict_group(
                storage,
                tenant,
                record_id,
                session_id,
                [m for m in conflict if m.order > -1],
                [m for m in conflict if m.order < 0],
                reference_curve=reference_curve,
            )
        )
    return chunk_metas_without_conflict


@capture_timings("find_conflicts")
def find_conflicts(chunk_meta_list: List[ChunkMeta]) -> List[List[ChunkMeta]]:
    # the following algo is a bit awful and tedious but main goal is to favor non conflicting cases
    # expected fast without or few conflicts, slower and slower with increasing number of conflict.
    # done using 2 rough passes, first on columns then refined on index range
    # then potential conflicting chunks are checked against each other
    # finally chunk in conflict (including transient conflict) are grouped

    all_cols: Set[str] = set()
    col_conflicted: Set[int] = set()
    direct_chunk_conflicts: Dict[int, Set[int]] = {}  # for a given chunk list all direct conflict

    # First pass ---------- any chunk that contains a columns that appears somewhere else in another
    # chunk (without knowing yet exactly with which ones)
    # favor proper vertical sliced chunk
    for i_ch_meta, chunk_meta in enumerate(chunk_meta_list):
        previous_len = len(all_cols)
        all_cols.update(chunk_meta.columns)
        if previous_len + len(chunk_meta.columns) > len(all_cols):
            col_conflicted.add(i_ch_meta)

    if len(col_conflicted) > 0:
        all_cols.clear()
        for i_ch_meta, chunk_meta in enumerate(reversed(chunk_meta_list)):
            previous_len = len(all_cols)
            all_cols.update(chunk_meta.columns)
            if previous_len + len(chunk_meta.columns) > len(all_cols):
                col_conflicted.add(len(chunk_meta_list) - i_ch_meta - 1)

    chunk_that_shared_columns = list(col_conflicted)

    # On columns that appears in several chunk, we check dtype are consistent across chunks
    # if inconsistent, for instance column `A` is type `int` in one chunk, but `str` on another, it raises, as it's an
    # unsolvable case
    # Note that different type is allowed if it shares the same kind, `int`, `int32` and `int64` share the same kind
    column_types: Dict[str, Set[str]] = {}
    for i_left_ch_meta in chunk_that_shared_columns:
        for column_label, column_type in chunk_meta_list[i_left_ch_meta].column_dtypes.items():
            column_types.setdefault(column_label, set()).add(column_type)

    column_with_mismatched_type = {label: types for label, types in column_types.items() if len(types) > 1}
    if column_with_mismatched_type:
        # refine as int, int32 and int64 remains valid
        mismatch_label_list = []
        for column_label, types in column_with_mismatched_type.items():
            try:
                kinds = {np.dtype(t).kind for t in types}
                if len(kinds) > 1:
                    mismatch_label_list.append(column_label)
            except TypeError:
                mismatch_label_list.append(column_label)
        if mismatch_label_list:
            raise BulkValidationError(f"heterogeneous data type detected for columns: {', '.join(mismatch_label_list)}")

    # Second pass ------- on columns against by looking for column shape misalignment
    # if column appears in two or more chunks, all these chunks should have the exact same columns otherwise
    # it's a column misalignment so it require a conflict resolution
    column_to_hashes: Dict[str, Set[str]] = dict()
    hash_to_chunk_index: Dict[str, Set[int]] = dict()
    for idx_ch_meta in col_conflicted:  # just need to do it on chunk than shared some columns
        ch = chunk_meta_list[idx_ch_meta]
        for column_label in ch.columns:
            column_to_hashes.setdefault(column_label, set()).add(ch.column_hash)
        hash_to_chunk_index.setdefault(ch.column_hash, set()).add(idx_ch_meta)

    for column_hashes in column_to_hashes.values():
        if len(column_hashes) > 1:  # meaning column appears in two or more different columns hashes = misalignment
            indexes = set().union(*[hash_to_chunk_index[h] for h in column_hashes])
            for idx in indexes:
                direct_chunk_conflicts.setdefault(idx, set()).update(indexes)

    # Third pass ------- refining column conflicted by checking overlap on index
    idx_conflict = set()
    for idx_1, idx_2 in combinations(chunk_that_shared_columns, 2):
        if chunk_meta_list[idx_1].index_overlap_with(chunk_meta_list[idx_2]):
            idx_conflict.add(idx_1)
            idx_conflict.add(idx_2)

    potential_conflict = idx_conflict.intersection(col_conflicted)

    # Final pass ------ checking all potential chunk in conflict against all other <=> O(n2)
    for idx_1, idx_2 in combinations(potential_conflict, 2):
        if chunk_meta_list[idx_1].overlap_with(chunk_meta_list[idx_2]):
            direct_chunk_conflicts.setdefault(idx_1, set()).add(idx_2)
            direct_chunk_conflicts.setdefault(idx_2, set()).add(idx_1)

    # group them, including transient conflict. If A conflict with B, B with C, but not directly A with C, then A, B, C
    # will be in same group anyway
    group_conflicting_chunks = []  # resolve transient conflict and group them together
    for i_ch_meta in list(direct_chunk_conflicts.keys()):  # use a list because the dict will be modified
        if i_ch_meta in direct_chunk_conflicts:
            all_conflict_transient: Set[int] = direct_chunk_conflicts[i_ch_meta]
            keep_grouping = True
            while keep_grouping:
                keep_grouping = False
                for j_ch_meta in list(all_conflict_transient):
                    if j_ch_meta != i_ch_meta and j_ch_meta in direct_chunk_conflicts:
                        all_conflict_transient.update(direct_chunk_conflicts[j_ch_meta])
                        del direct_chunk_conflicts[j_ch_meta]
                        keep_grouping = True
            direct_chunk_conflicts.pop(i_ch_meta, None)
            group_conflicting_chunks.append(all_conflict_transient)

    result = []
    for group_id, indexes in enumerate(group_conflicting_chunks):
        group = []
        for i_left_ch_meta in indexes:
            chunk_meta_list[i_left_ch_meta].conflict_group_id = group_id
            group.append(chunk_meta_list[i_left_ch_meta])
        result.append(group)

    return result
