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

"""
This module groups function related to bulk catalog.
A catalog contains metadata of the chunks
"""
import json
from contextlib import suppress
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Set, Tuple, Dict
from itertools import chain
from io import BytesIO
from asyncio import create_task

import pandas as pd

from osdu.core.api.storage.blob_storage_base import BlobStorageBase
from osdu.core.api.storage.exceptions import ResourceNotFoundException

from . import storage_path_builder
from .dataframe import (
    ColumnSelection,
    get_requested_columns,
    sort_column_labels,
    group_curve_columns,
    dump_to_parquet,
    columns_to_slices,
)
from .chunk_meta import ChunkMeta
from ..capture_timings import timeit, capture_timings
from .storage_path_builder import catalog_file_path, record_relative_path, join


@dataclass
class ChunkGroup:
    """
    A chunk group represent a chunk list having exactly the same schemas
    (columns labels and dtypes).
    Attributes:
        - labels: Set[str]: set of columns labels
        - paths: List[str]: list of path of the chunks, path is relative to record root path, therefore relative to path
                            built using `storage_path_builder.record_path_level_0` since chunks may comes from various
                            sessions
    """

    labels: Set[str]
    paths: List[str]


ColumnLabel = str


class BulkCatalogOrigin:
    def __init__(self):
        self._origin_type = 0  # internal, 0 = unknown, 1 = generated from bulk, 2 loaded from file

    @classmethod
    def from_file(cls):
        inst = cls()
        inst._origin_type = 2
        return inst

    @classmethod
    def generated_from_bulk(cls):
        inst = cls()
        inst._origin_type = 1
        return inst

    @property
    def was_generated(self) -> bool:
        return self._origin_type == 1


class BulkCatalog:
    """
    Represent a bulk catalog. Note: all path are expected to be relative to the record root folder
    Example:
        {
            "fileVersion": "2",
            "recordId": "7507fb30-9cfa-4506-9cd8-6cbacbcda740",
            "nbRows": 1000,
            "indexPath": "folder/wdms_index/index.parquet,
            "columns" : [
                {
                    "labels": ["A", "B"],
                    "paths": ["folder/file1.parquet", "folder/file2.parquet"],
                },
                {
                    "labels": ["C"],
                    "paths": ["folder/file3.parquet"],
                }
            ],
        }
    """

    file_version = "2"

    def __init__(
        self,
        record_id: str,
        nb_rows: int = 0,
        index_path: str | None = None,
        chunk_groups: List[ChunkGroup] | None = None,
        origin: BulkCatalogOrigin | None = None,
    ) -> None:
        self._record_id: str = record_id
        self.nb_rows: int = nb_rows
        self.index_path: str | None = index_path
        self._columns: List[ChunkGroup] = chunk_groups or []
        self.origin = origin or BulkCatalogOrigin()  # not persisted
        self.reference: str | None = None

        self._curves: Dict[str, int] | None = None

        # cached attributes, cleaned as soon as _columns change
        self._columns_labels: Set[str] | None = None

    @property
    def curves(self) -> Dict[str, int]:
        if self._curves is None:
            grouped_curves = group_curve_columns(self.all_columns, include_non_array=True)
            self._curves = {label: len(columns) for label, columns in grouped_curves.items()}
        return self._curves

    @classmethod
    def from_metas(
        cls,
        record_id: str,
        chunk_metas: List[ChunkMeta],
        *,
        nb_rows: int = 0,
        global_index: pd.Index | pd.Series | pd.DataFrame | None = None,
    ) -> "BulkCatalog":
        """
        build a catalog from chunk meta. Chunks are expected to be provided without any conflicts/overlaps.
        all path put inside the catalog are related to the record root path aka `record_path_level_0`.
        :param record_id:
        :param chunk_metas: file base path must be set inside chunk meta
        :param nb_rows:
        :param global_index: if provided, nb_row is extracted from it
        :return:
        """

        # group chunk metas by columns shape
        metas_by_columns: Dict[str, List[ChunkMeta]] = {}
        for m in chunk_metas:
            metas_by_columns.setdefault(m.column_hash, []).append(m)

        record_root_path = storage_path_builder.record_path_level_0(record_id)
        chunk_groups: List[ChunkGroup] = []
        for chunks in metas_by_columns.values():
            if chunks:
                chunk_groups.append(
                    ChunkGroup(
                        labels=set(chunks[0].columns_set),
                        paths=[c.get_filepath(ChunkMeta.FileType.CHUNK, relative_to=record_root_path) for c in chunks],
                    )
                )
        if global_index is not None:
            nb_rows = len(global_index)
        return cls(record_id, nb_rows, None, chunk_groups)

    @property
    def record_id(self) -> str:
        return self._record_id

    @property
    def nb_columns(self) -> int:
        """
        Return number of columns contained in bulk data
        """
        return len(self.all_columns)

    def is_columns_slide_only(self, columns_to_check: Set[str] | None = None) -> bool:
        """
        return True if the bulk is only cut by columns, i.e. there's one and only one chunk to read to get full column
        """
        column_label_set: Set[str] = set()
        previous_size = 0
        if columns_to_check is None:
            for chunk_group in self._columns:
                if len(chunk_group.paths) > 1:
                    return False
                column_label_set.update(chunk_group.labels)
                if previous_size + len(chunk_group.labels) > len(column_label_set):
                    return False
                previous_size = len(column_label_set)
            return True

        # case few columns only
        for chunk_group in self._columns:
            intersect = chunk_group.labels.intersection(columns_to_check)
            if not intersect:
                continue

            if len(chunk_group.paths) > 1:
                return False

            if not column_label_set.isdisjoint(intersect):
                # it's mean there's already on chunk for one element in intersect
                return False
            column_label_set.update(intersect)

        return True

    def _clean_column_cache(self):
        self._columns_labels = None

    def add_index_path(self, bulk_id: str):
        """
        fill up index path given the bulk_id, index is unique per bulk_id
        :param bulk_id:
        """
        self.index_path = join(storage_path_builder.bulk_path_level_1(None, bulk_id), "_wdms_index_", "index.parquet")

    @property
    def all_columns(self) -> Set[str]:
        if self._columns_labels is None:
            self._columns_labels = set(chain.from_iterable((col_group.labels for col_group in self._columns)))
        return self._columns_labels

    @property
    def chunk_count(self) -> int:
        # TODO by design, a path should not appear twice but nothing prevent to construct a catalog with the same
        #  chunk path more than once, so let's use a set container for now
        return len(set(self.get_chunk_paths()))

    def get_chunk_paths(self) -> Iterator[str]:
        """iterator over all paths, not path are provided relative to the record root dir"""
        return chain.from_iterable((col_group.paths for col_group in self._columns))

    def get_chunk_columns(self) -> Iterator[Tuple[str, Set[str]]]:
        """
        :return: iterator [chunk path, chunk column labels]
        """
        # by design and conflict resolution rules, chunk cannot appear twice
        for col_group in self._columns:
            for p in col_group.paths:
                yield p, col_group.labels

    def get_chunk_columns_slices(self) -> Iterator[List[str]]:
        """
        :return: iterator list of columns of each chunk using slice expression
        """
        # by design and conflict resolution rules, chunk cannot appear twice
        for col_group in self._columns:
            yield columns_to_slices(col_group.labels)

    def get_absolut_chunk_paths(self) -> Iterator[str]:
        """same as `get_chunk_path but with absolut path"""
        record_root_dir = storage_path_builder.record_path_level_0(self.record_id)
        for p in self.get_chunk_paths():
            yield storage_path_builder.join(record_root_dir, p)

    @staticmethod
    def is_single_file_chunk(chunk_path) -> bool:
        """differentiate a single chunk from a multi partition dataframe saved by Dask. returns True if chunk is a
        lonely parquet file"""
        # so far the simplest and fastest (loose) way is to check if the file_name match a chunk file name generated
        # from session_file_meta. Luckily the only way chunk is generated using Dask is when conflict resolution
        # happen and the name format is different (just a uuid)
        # Another way would be to check is the path point to a file (raw chunk) or a folder (Dask multi partition)
        return ChunkMeta.is_a_chunk_file(chunk_path)

    # TODO to move in unit test: performance bottleneck detected
    def add_chunk(self, chunk_group: ChunkGroup) -> None:
        """Add ChunkGroup to the catalog."""
        if len(chunk_group.labels) == 0:
            return

        self._clean_column_cache()
        keys = frozenset(chunk_group.labels)
        chunk_group_with_same_schema = next(
            (x for x in self._columns if len(keys) == len(x.labels) and all(label in keys for label in x.labels)), None
        )
        if chunk_group_with_same_schema:
            chunk_group_with_same_schema.paths.extend(chunk_group.paths)
        else:
            self._columns.append(chunk_group)

    def filter_group_for_columns(self, labels: Iterable[str] | None) -> List[ChunkGroup]:
        if labels:
            return [col_group for col_group in self._columns if not col_group.labels.isdisjoint(labels)]
        return self._columns

    def as_dict(self) -> dict:
        """Returns the dict representation of the catalog"""
        return {
            "recordId": self.record_id,
            "nbRows": self.nb_rows,
            "indexPath": self.index_path,
            "columns": [{"labels": list(c.labels), "paths": c.paths} for c in self._columns],
            "curves": self.curves,
            "reference": self.reference,
            "version": self.file_version,
        }

    def describe(
        self,
        *,
        offset: int | None = None,
        limit: int | None = None,
        column_selection: ColumnSelection | None = None,
    ) -> Tuple[int, List[str]]:
        """
        Retrieve from the catalog the number of rows and list of columns of the bulk data
        :param offset: The number of rows that are to be skipped and not included in the result
        :param limit: The maximum number of rows to be returned
        :param column_selection: List of columns to be returned (act as filter)
        :return: The number of rows and the list of columns
        """
        nb_rows = self.nb_rows
        if offset:
            nb_rows = max(0, nb_rows - offset)
        if limit:
            nb_rows = min(nb_rows, limit)

        if column_selection:
            columns, _, _ = get_requested_columns(column_selection, self.all_columns)
        else:
            with timeit(f"sort {len(self.all_columns)} columns using natsorted"):
                columns = sort_column_labels(self.all_columns)

        return nb_rows, columns

    @classmethod
    def from_dict(cls, catalog_as_dict: dict) -> "BulkCatalog":
        """construct a Catalog from a dict"""
        catalog = cls(record_id=catalog_as_dict["recordId"])
        catalog.nb_rows = catalog_as_dict["nbRows"]
        catalog.index_path = catalog_as_dict["indexPath"]
        catalog._columns = [ChunkGroup(set(c["labels"]), c["paths"]) for c in catalog_as_dict["columns"]]
        catalog._curves = catalog_as_dict.get("curves")
        catalog.reference = catalog_as_dict.get("reference")
        catalog.file_version = catalog_as_dict.get("version", "1")  # if version not there, assume previous version
        return catalog

    @classmethod
    def from_single_dataframe(cls, record_id: str, path: str, dataframe: pd.DataFrame) -> "BulkCatalog":
        rel_path = record_relative_path(record_id, path, base_directory=None)

        catalog = cls(record_id)
        catalog.nb_rows = dataframe.shape[0]
        catalog._columns.append(
            ChunkGroup(
                labels=set(dataframe.columns),  # TODO review as it lost order + relation to dtypes
                paths=[rel_path],
            )
        )
        return catalog


@capture_timings("async_load_bulk_catalog_with_blob_storage")
async def async_load_bulk_catalog_with_blob_storage(
    storage: BlobStorageBase, tenant, record_id: str, bulk_id: str
) -> BulkCatalog | None:
    storage_full_name = catalog_file_path(record_id, bulk_id, base_directory=None)
    with suppress(ResourceNotFoundException):
        with timeit("async download bulk_catalog"):
            content = await storage.download(tenant, storage_full_name)

        with timeit(f"parse download bulk_catalog of size {len(content)}"):
            data = json.load(BytesIO(content))
            return BulkCatalog.from_dict(data)
    return None


@capture_timings("async_save_bulk_catalog_with_blob_storage")
async def async_save_bulk_catalog_with_blob_storage(
    storage: BlobStorageBase,
    tenant,
    bulk_id: str,
    catalog: BulkCatalog,
    index_df: pd.Index | pd.DataFrame | None = None,
    reference: str | None = None,
) -> None:
    catalog.reference = reference
    storage_full_name = catalog_file_path(catalog.record_id, bulk_id, base_directory=None)
    upload_index_task = None
    if index_df is not None:
        if isinstance(index_df, pd.Index):
            index_df = pd.DataFrame(index=index_df)
        else:
            # TODO input dataframe may contains reference values also, not sure if it worth keeping these values
            #  separated to speed up some workflow read .
            index_df = pd.DataFrame(index=index_df.index)

        catalog.add_index_path(bulk_id)
        upload_index_task = create_task(
            storage.upload(
                tenant,
                join(storage_path_builder.record_path_level_0(catalog.record_id), catalog.index_path),
                dump_to_parquet(index_df),
            )
        )

    with timeit("json dumps bulk_catalog"):
        json_bytes = json.dumps(catalog.as_dict(), indent=0).encode()

    with timeit(f"upload bulk_catalog of size {len(json_bytes)}"):
        await storage.upload(tenant, storage_full_name, BytesIO(json_bytes))

    if upload_index_task is not None:
        await upload_index_task
