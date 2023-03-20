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

from typing import List, Set, Dict

# TODO [TAG pandas dependent]
import pandas as pd

from .bulk_storage_version import BulkStorageVersion
from .storage_path_builder import basename


# rework from SessionFileMeta
class ChunkMeta:
    """Gather extended information about chunks"""

    StorageVersion = BulkStorageVersion.V2

    def __init__(
        self, filepath: str, columns: List[str], dtypes: List[str], index_dtype: str, index_start, index_end, nb_rows
    ):
        self.filepath = filepath
        self.index_hash, self.column_hash, self.filename = self._expand_filepath(filepath)
        self._columns = dict.fromkeys(columns)
        self._dtypes = dtypes  # ChunkMeta._expand_columns(columns, dtypes)
        self.index_dtype = index_dtype
        self.index_start = index_start
        self.index_end = index_end
        self._ordered_range = (index_start, index_end) if index_end > index_start else (index_end, index_start)
        self.nb_rows = nb_rows

    @property
    def columns(self) -> List[str]:
        return list(self._columns.keys())

    @property
    def dtypes(self) -> List[str]:
        return self._dtypes

    def share_columns_with(self, other: "ChunkMeta"):
        return not self._columns.keys().isdisjoint(other._columns.keys())

    def index_overlap_with(self, other: "ChunkMeta"):
        r1 = self._ordered_range
        r2 = other._ordered_range
        return not (r2[0] > r1[1] or r2[1] < r1[0])

    def overlap_with(self, other: "ChunkMeta") -> bool:
        return self.share_columns_with(other) and self.index_overlap_with(other)

    @classmethod
    def _expand_filepath(cls, filepath: str):
        filename = basename(filepath)
        index_hash, column_hash, _ = filename.split(".")
        return index_hash, column_hash, filename

    @classmethod
    def _expand_columns(cls, columns, dtypes):
        """
        expand columns when using slice notation, e.g. C[2:5] ==> C[2], C[3], c[4], C[5]
        arrays are homogenous so same dtypes for all
        """
        # TODO not supported yet
        return columns, dtypes

    @classmethod
    def _make_index_value_dump_fn(cls, dtype: str):
        if "int" in dtype:
            return lambda x: int(x)
        if "float" in dtype:
            return lambda x: float(x)
        if "time" in dtype:
            return lambda x: int(x.value)  # this will provide date time as integer usually with nanosecond precision
        raise ValueError("unsupported index type")

    @classmethod
    def load(cls, filepath: str, content: bytes) -> "ChunkMeta":
        from io import BytesIO
        import json

        meta_dict = json.load(BytesIO(content))
        return cls(
            filepath,
            meta_dict["columns"],
            meta_dict["dtypes"],
            meta_dict["index_dtype"],
            meta_dict["index_start"],
            meta_dict["index_end"],
            meta_dict["nb_rows"],
        )

    # TODO [TAG pandas dependent]
    @classmethod
    def from_dataframe(cls, filepath: str, df: pd.DataFrame) -> "ChunkMeta":
        idx = df.index
        dump_index = cls._make_index_value_dump_fn(str(idx.dtype))
        dtypes = df.dtypes.values

        return cls(
            filepath,
            df.columns.to_list(),
            [str(d) for d in dtypes],  # [str(dtypes[0])] if np.all(dtypes == dtypes[0]) else [str(d) for d in dtypes],
            str(idx.dtype),
            dump_index(idx[0]),
            dump_index(idx[-1]),
            len(idx),
        )

    def dump(self) -> bytes:
        import json

        columns, dtypes = self._expand_columns(self._columns, self._dtypes)
        return json.dumps(
            {
                "columns": columns,
                "dtypes": dtypes,
                "index_dtype": self.index_dtype,
                "index_start": self.index_start,
                "index_end": self.index_end,
                "nb_rows": self.nb_rows,
            }
        ).encode()


def find_conflicts(chunk_meta_list: List[ChunkMeta]) -> List[List[ChunkMeta]]:
    # TODO: to be reviewed
    # the following algo is a bit awful and tedious but main goal is to favor non conflicting cases
    # expected fast without or few conflicts, slower and slower with increasing number of conflict.
    # done using 2 rough passes, first on columns then refined on index range
    # then potential conflicting chunks are checked against each other
    # finally chunk in conflict (including transient conflict) are grouped

    all_cols: Set[str] = set()
    col_conflicted: Set[int] = set()

    # first rough pass on columns
    for i, lhs in enumerate(chunk_meta_list):
        previous_len = len(all_cols)
        all_cols.update(lhs._columns)
        if previous_len + len(lhs._columns) > len(all_cols):
            col_conflicted.add(i)

    if len(col_conflicted) > 0:
        all_cols.clear()
        for i, lhs in enumerate(reversed(chunk_meta_list)):
            previous_len = len(all_cols)
            all_cols.update(lhs._columns)
            if previous_len + len(lhs._columns) > len(all_cols):
                col_conflicted.add(len(chunk_meta_list) - i - 1)

    # refined column conflicted by checking overlap on index
    col_conflicted_as_list = list(col_conflicted)
    idx_conflict = set()
    for e, i in enumerate(col_conflicted_as_list):
        lhs = chunk_meta_list[i]
        for j in col_conflicted_as_list[e + 1 :]:
            rhs = chunk_meta_list[j]
            if lhs.index_overlap_with(rhs):
                idx_conflict.add(i)
                idx_conflict.add(j)

    potential_conflict = idx_conflict.intersection(col_conflicted)

    # checking all potential chunk in conflict against all other <=> O(n2)
    individual_chunk_conflicts: Dict[int, Set[int]] = {}  # for a given chunk list all direct conflict
    potential_conflict_as_list = list(potential_conflict)
    for e, i in enumerate(potential_conflict_as_list):
        lhs = chunk_meta_list[i]
        for j in potential_conflict_as_list[e + 1 :]:
            rhs = chunk_meta_list[j]
            if lhs.overlap_with(rhs):
                individual_chunk_conflicts.setdefault(i, set()).add(j)
                individual_chunk_conflicts.setdefault(j, set()).add(i)

    # group them, including transient conflict. If A conflict with B, B with C, but not directly A with C, then A, B, C
    # will be in same group anyway
    group_conflicting_chunks = []  # resolve transient conflict and group them together
    for k in list(individual_chunk_conflicts.keys()):  # use a list because the dict will be modified
        if k in individual_chunk_conflicts:
            all_conflict_transient: Set[int] = individual_chunk_conflicts[k]
            keep_grouping = True
            while keep_grouping:
                keep_grouping = False
                for c in list(all_conflict_transient):
                    if c != k and c in individual_chunk_conflicts:
                        all_conflict_transient.update(individual_chunk_conflicts[c])
                        del individual_chunk_conflicts[c]
                        keep_grouping = True
            individual_chunk_conflicts.pop(k, None)
            group_conflicting_chunks.append(all_conflict_transient)

    return [[chunk_meta_list[i] for i in g] for g in group_conflicting_chunks]
