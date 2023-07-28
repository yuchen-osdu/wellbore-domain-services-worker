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

""" Module containing high level functions to write bulk data """
import uuid
from enum import Enum
from typing import Tuple, List
from functools import reduce
from os.path import dirname, basename
from asyncio import create_task, gather

import pandas as pd

from osdu.core.api.storage.blob_storage_base import BlobStorageBase
from osdu.core.api.storage.exceptions import ResourceNotFoundException

from .chunk_storage import upload_chunk, upload_index_from_chunk
from .chunk_meta import ChunkMeta, sort_chunk_metas_by_index
from .conflict import resolve_conflicts
from .reader import get_chunk_path_outside_session, load_same_shape_dataframes_from_storage
from . import storage_path_builder
from .dataframe import load_df, load_parquet, basic_describe, dump_to_parquet
from .catalog import BulkCatalog, async_save_bulk_catalog_with_blob_storage, async_load_bulk_catalog_with_blob_storage
from .validators import validate_df
from ..model.describe import DataframeBasicDescribe, ColumnDescribe
from ..model.mime_types import MimeType, MimeTypes
from . import errors as exc
from ..logger import get_logger
from ..capture_timings import capture_timings, timeit


def new_bulk_id() -> str:
    """:return: new bulk id"""
    return str(uuid.uuid4())


@capture_timings("write_chunk")
async def write_bulk_data_in_session(
    storage: BlobStorageBase,
    tenant,
    content: bytes,
    content_type: MimeType,
    record_id: str,
    session_id: str,
    *,
    reference_curve: str | None = None,
) -> DataframeBasicDescribe:
    """
    Add a bulk chunk within a session
    :param storage:
    :param tenant:
    :param content:
    :param content_type:
    :param record_id:
    :param session_id:
    :param reference_curve:
    :return:
    :throws: BulkValidationError, BulkUploadFailure
    """
    # deserialize the dataframe
    try:
        df = load_df(content, content_type)
    except Exception as e:
        raise exc.BulkUnprocessableError() from e

    if df.empty:
        return basic_describe(df, reference_name=None)

    await upload_chunk(
        storage,
        tenant,
        df,
        content if content_type == MimeTypes.PARQUET else None,
        record_id,
        session_id,
        reference_curve=reference_curve,
    )

    return basic_describe(df, reference_name=None)


@capture_timings("_get_chunks_metadata")
async def _get_chunks_metadata(storage: BlobStorageBase, tenant, record_id: str, session_id: str) -> List[ChunkMeta]:
    """Return metadata objects for a given session"""
    session_path = storage_path_builder.session_path_level_1(record_id, session_id, base_directory=None)
    all_objs = await storage.list_objects(tenant, prefix=session_path)
    all_metas = list(filter(MimeTypes.META.match_extension, all_objs))

    async def _load_single_meta(s, t, f) -> ChunkMeta:
        content = await s.download(t, f)
        return ChunkMeta.load(f, content)

    with timeit(f"get_chunks_metadata {len(all_metas)} meta files"):
        # TODO should we restrict the number of concurrency here,
        return list(await gather(*[_load_single_meta(storage, tenant, o) for o in all_metas]))


async def _load_or_create_chunk_metadata(
    storage: BlobStorageBase,
    tenant,
    object_path: str,
    reference_curve: str | None = None,
) -> ChunkMeta:
    """
    straight load chunk metadata if exist and latest version. Otherwise built it and upload it for future usage
    :param storage:
    :param tenant:
    :param object_path: chunk parquet file path
    :return: chunk meta data
    """

    chunk_meta_path = MimeTypes.META.replace_extension(object_path, MimeTypes.PARQUET)
    must_create = False
    try:
        chunk_meta_content = await storage.download(tenant, chunk_meta_path)
        chunk_meta = ChunkMeta.load(chunk_meta_path, chunk_meta_content)

        # check if reference curve info are present in meta, otherwise
        if reference_curve and not chunk_meta.has_reference and reference_curve in chunk_meta.columns_set:
            get_logger().info(f"chunk meta {object_path} does not contain reference info - rebuild it")
            must_create = True

    except ResourceNotFoundException:
        # unfortunately need to build it from the chunk data
        get_logger().info(f"no chunk meta found for {object_path} - build it")
        must_create = True

    if must_create:
        chunk_df = await load_same_shape_dataframes_from_storage(storage, tenant, [object_path])
        chunk_meta = ChunkMeta.from_dataframe(
            chunk_df, dirname(object_path), basename(object_path), reference_curve=reference_curve
        )

    if chunk_meta.origin != ChunkMeta.Origin.META_V2:
        # if just created (i.e. origin = DATAFRAME) or loaded from previous format (origin = META_V1). Let's upload
        # it for future usage, potentially overwriting previous one (origin will be META_V2 the next reload)
        create_task(
            storage.upload(tenant, MimeTypes.META.add_extension(object_path), chunk_meta.dump()),
        )

    return chunk_meta


async def load_index_from_chunk(storage: BlobStorageBase, tenant, chunk_meta: ChunkMeta) -> pd.DataFrame:
    """
    download and load index dataframe from chunk meta. If not exist, creates it
    :param storage:
    :param tenant:
    :param chunk_meta:
    :return: index only dataframe
    """
    try:
        parquet_content = await storage.download(tenant, chunk_meta.get_filepath(ChunkMeta.FileType.INDEX))
        return load_parquet(parquet_content)
    except ResourceNotFoundException:
        # standalone index doesn't exist, make it from the chunk directly
        get_logger().error(f"index dataframe not found chunk {chunk_meta.filename}, rebuilt from stored dataframe")
        df = await load_same_shape_dataframes_from_storage(
            storage, tenant, [chunk_meta.get_filepath(ChunkMeta.FileType.CHUNK)]
        )
        return await upload_index_from_chunk(storage, tenant, chunk_meta, df, overwrite=True)


@capture_timings("build index")
async def build_index(
    storage: BlobStorageBase,
    tenant,
    chunk_metas: List[ChunkMeta],
) -> pd.DataFrame:
    """
    construct entire index dataframe from all chunks meta. If a reference curve is provided, the returned dataframe
    will also contain the corresponding column and values.
    Do not support conflicted chunk, therefore conflicts must be resolved before.
    :param storage:
    :param tenant:
    :param chunk_metas:
    :return:
    """

    by_index = {m.index_hash: m for m in chunk_metas}

    # load all different indexes then merge them all, in best case scenario indexes were already uploaded alone,
    # if not, one of chunk is loaded to extract the index from it. In general very few load are needed, actually
    # only one in most use cases
    load_coros = [load_index_from_chunk(storage, tenant, m) for m in by_index.values()]
    with timeit(f"build_index from {len(load_coros)} chunk(s)"):
        global_indexes = await gather(*load_coros)
        global_index = pd.DataFrame(index=reduce(lambda acc, idx: acc.union(idx), (i.index for i in global_indexes)))

    return global_index


@capture_timings("complete_session")
async def complete_session(
    storage: BlobStorageBase,
    tenant,
    record_id: str,
    session_id: str,
    commit_mode: str,
    previous_bulk: str | None = None,
    reference_curve: str | None = None,
) -> Tuple[str, DataframeBasicDescribe]:
    if not previous_bulk:
        commit_mode = SessionCompletionMode.Overwrite

    # let's gather all chunk metas of this session
    chunk_metas = await _get_chunks_metadata(storage, tenant, record_id, session_id)
    previous_chunk_metas = None
    if not chunk_metas:
        raise exc.BulkCommitNoDataError()

    if commit_mode == SessionCompletionMode.Update:
        with timeit("commit session - update"):
            # there are several cases to handle:
            #   - no catalog = single bulk without either Dask without session or V0, no chunk meta
            #   - catalog => built from dask, may be chunk meta but in previous format
            #   - catalog => build from worker, always chunk meta
            previous_catalog = await async_load_bulk_catalog_with_blob_storage(
                storage, tenant, record_id, previous_bulk
            )

            if previous_catalog is not None:
                # let's load the chunk metas
                previous_chunk_metas = await gather(
                    *[
                        _load_or_create_chunk_metadata(storage, tenant, p, reference_curve)
                        for p in previous_catalog.get_absolut_chunk_paths()
                    ]
                )
            else:
                get_logger().info("updating from previous without catalog")
                chunk_path = await get_chunk_path_outside_session(storage, tenant, record_id, previous_bulk)  # type: ignore
                ch_meta = await _load_or_create_chunk_metadata(storage, tenant, chunk_path, reference_curve)
                previous_chunk_metas = [ch_meta]

    chunk_metas = await resolve_conflicts(
        storage, tenant, record_id, session_id, chunk_metas, previous_chunk_metas, reference_curve=reference_curve
    )

    bulk_id = new_bulk_id()

    # build catalog and index
    catalog = BulkCatalog.from_metas(record_id, chunk_metas)
    global_index = await build_index(storage, tenant, chunk_metas)
    catalog.nb_rows = len(global_index)

    if reference_curve:
        # build reference description from chunk meta, this is valid because at this stage chunk no longer overlaps
        # and info remains valid from separated ordered chunk
        chunk_metas_ref = sort_chunk_metas_by_index(list(m for m in chunk_metas if m.reference_name == reference_curve))

        # validate reference values covers the entire index, global index, by design, covers any columns, the reference
        # included, then checking values counts is enough
        # Note: it also handle case `chunk_meta_ref` empty since `sum` will return 0
        ref_values_count = sum(m.nb_rows for m in chunk_metas_ref)
        if ref_values_count != len(global_index):
            raise exc.BulkValidationError(
                f"reference curve '{reference_curve}' do not cover the entire bulk,"
                f" {len(global_index)-ref_values_count} values are missing."
            )

        # build reference info
        ranged_ref_df = pd.concat(m.start_end_df() for m in chunk_metas_ref)

        # still validate to catch early on invalid reference
        validate_df(ranged_ref_df, reference_curve)

        # Note: `hasNaN` and `hasDuplicate` will always `False` and `False` by construction, these properties are
        # validated on the fly on post bulk/chunk (see `validate_df`) or during conflict resolution. Reference unicity
        # across chunks will be caught either because of non homogeneous order or non monotonic from ref edges.
        reference = ColumnDescribe.from_column(ranged_ref_df, reference_curve)
    else:
        reference = ColumnDescribe.from_index(global_index)

    await async_save_bulk_catalog_with_blob_storage(storage, tenant, bulk_id, catalog, global_index, reference_curve)

    return bulk_id, DataframeBasicDescribe(rowCount=len(global_index), curves=catalog.curves, reference=reference)


@capture_timings("write_bulk")
async def write_bulk(
    storage: BlobStorageBase,
    tenant,
    content: bytes,
    content_type: MimeType,
    record_id: str,
    reference_curve: str | None = None,
) -> Tuple[str, DataframeBasicDescribe]:
    """
    Write whole bulk (no session)
    :param storage:
    :param tenant:
    :param content:
    :param content_type:
    :param record_id:
    :param reference_curve: name of the reference curve, if not `None` will return a describe of it
    :return: tuple bulkid, describe
    :throws: BulkValidationError, BulkUploadFailure, BulkUnprocessable
    """

    # 1- deserialize the dataframe
    try:
        df = load_df(content, content_type)
    except Exception as e:
        raise exc.BulkUnprocessableError() from e

    if df.empty:
        raise exc.BulkUnprocessableError("empty bulk")

    # 2- validate df
    from .validators import validate_df

    validate_df(df, reference_curve)

    df_description = basic_describe(df, reference_curve)

    # TODO use upload chunk

    # create chunk meta - useful for potential later updates
    chunk_meta = ChunkMeta.from_dataframe(df, reference_curve=reference_curve)

    # 3- build blob filename
    bulk_id = new_bulk_id()
    bulk_base_path = storage_path_builder.bulk_path_level_1(record_id=record_id, bulk_id=bulk_id, base_directory=None)
    full_file_path = storage_path_builder.join(bulk_base_path, chunk_meta.filename + ".parquet")

    content_to_upload: str | bytes = content
    if content_type == MimeTypes.JSON:  # we don't need to serialize if already in parquet
        content_to_upload = dump_to_parquet(df)

    # 4- generate catalog
    catalog = BulkCatalog.from_single_dataframe(record_id, full_file_path, df)

    try:
        # 5- both upload catalog and data
        await gather(
            async_save_bulk_catalog_with_blob_storage(storage, tenant, bulk_id, catalog, None, reference_curve),
            storage.upload(tenant, full_file_path, content_to_upload),
            storage.upload(
                tenant, storage_path_builder.join(bulk_base_path, chunk_meta.filename_with_extension), chunk_meta.dump()
            ),
        )

    except Exception as e:
        get_logger().exception(f"Exception occurred while uploading to blob storage for record {record_id}")
        raise exc.BulkUploadError("Failed to store bulk and its metadata") from e

    return bulk_id, df_description


class SessionCompletionMode(str, Enum):
    # abandon
    Abandon = "abandon"

    # commit modes
    Overwrite = "overwrite"
    Update = "update"
