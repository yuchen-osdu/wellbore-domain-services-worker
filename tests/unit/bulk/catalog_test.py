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

import uuid

import pandas as pd
import pytest
from osdu.core.api.storage.blob_storage_base import BlobStorageBase

from wdmsworker.bulk.catalog import (
    BulkCatalog,
    ChunkGroup,
    async_load_bulk_catalog_with_blob_storage,
    async_save_bulk_catalog_with_blob_storage,
)
from wdmsworker.bulk.chunk_meta import ChunkMeta
from wdmsworker.bulk import storage_path_builder

from ..generate_data import generate_df


def test_empty_catalog():
    catalog = BulkCatalog("id")
    assert catalog.chunk_count == 0
    d = catalog.as_dict()
    assert d["recordId"] == "id"
    assert d["nbRows"] == 0
    assert d["indexPath"] is None


def test_filter_group_for_columns():
    catalog = BulkCatalog("id")
    chunk_group1 = ChunkGroup({"A", "B"}, ["path1", "paths2"])
    catalog.add_chunk(chunk_group1)
    chunk_group2 = ChunkGroup({"C", "D"}, ["path3"])
    catalog.add_chunk(chunk_group2)

    assert catalog.filter_group_for_columns({"A"}) == [chunk_group1]
    assert catalog.filter_group_for_columns({"A", "B"}) == [chunk_group1]
    assert catalog.filter_group_for_columns({"C", "B"}) == [chunk_group1, chunk_group2]
    assert catalog.filter_group_for_columns({"D"}) == [chunk_group2]
    assert catalog.filter_group_for_columns({"Z"}) == []


def test_is_columns_slide_only():
    catalog = BulkCatalog("id")
    chunk_group = ChunkGroup({"A", "B"}, ["path1", "paths2"])
    catalog.add_chunk(chunk_group)
    chunk_group = ChunkGroup({"C", "D"}, ["path3"])
    catalog.add_chunk(chunk_group)

    assert not catalog.is_columns_slide_only()
    assert not catalog.is_columns_slide_only({"A"})
    assert not catalog.is_columns_slide_only({"A", "B"})
    assert not catalog.is_columns_slide_only({"A", "C"})
    assert catalog.is_columns_slide_only({"C"})
    assert catalog.is_columns_slide_only({"D", "C"})

    catalog = BulkCatalog("id")
    assert catalog.is_columns_slide_only()
    assert catalog.is_columns_slide_only({"C", "D", "A", "B"})


def test_is_columns_slide_only_handle_many_columns():
    # 400 chunks with 500 columns each
    catalog = BulkCatalog("id")
    for i in range(400):
        catalog.add_chunk(ChunkGroup({f"C{i}[{j}]" for j in range(500)}, [f"path{i}"]))

    assert catalog.is_columns_slide_only()
    assert catalog.is_columns_slide_only({f"C{i}[{j}]" for j in range(10, 70) for i in (3, 5, 100, 244)})

    catalog.add_chunk(ChunkGroup({"C2[50]"}, [f"pathX"]))
    assert not catalog.is_columns_slide_only()
    assert catalog.is_columns_slide_only({f"C{i}[{j}]" for j in range(10, 70) for i in (3, 5, 100, 244)})
    assert not catalog.is_columns_slide_only({"C2[50]"})


def test_build_catalog_single_chunk():
    catalog = BulkCatalog.from_single_dataframe(
        "record_id", "dir1/dir2/file.parquet", pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]}, index=[0, 1, 2])
    )

    assert catalog.nb_rows == 3
    assert catalog.record_id == "record_id"
    assert catalog.all_columns == {"A", "B"}
    catalog_dict = catalog.as_dict()
    assert len(catalog_dict["columns"]) == 1
    assert len(catalog_dict["columns"][0]["paths"]) == 1
    assert "dir1/dir2/file.parquet" in catalog_dict["columns"][0]["paths"][0]


@pytest.mark.anyio
async def test_save_load_catalog(bulk_storage_mock: BlobStorageBase, test_tenant):
    catalog = BulkCatalog.from_single_dataframe(
        "record_id", "dir1/dir2/file.parquet", pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]}, index=[0, 1, 2])
    )
    bulk_id = str(uuid.uuid4())
    await async_save_bulk_catalog_with_blob_storage(bulk_storage_mock, test_tenant, bulk_id, catalog)

    reloaded_catalog = await async_load_bulk_catalog_with_blob_storage(
        bulk_storage_mock, test_tenant, "record_id", bulk_id
    )

    assert catalog.record_id == reloaded_catalog.record_id
    assert catalog.nb_rows == reloaded_catalog.nb_rows
    assert catalog.index_path == reloaded_catalog.index_path
    assert catalog.all_columns == reloaded_catalog.all_columns


def test_describe_column_selection():
    catalog = BulkCatalog("id")
    catalog.add_chunk(ChunkGroup({"A", "B", "C"}, [f"pathA", f"pathB", f"pathC"]))

    nb_r, cols = catalog.describe(column_selection=["B", "A"])
    assert nb_r == 0
    assert cols == ["B", "A"]


@pytest.mark.slow
def test_describe_many_columns():
    # mainly to track time of the test
    # as it could be a bottleneck for big array

    catalog = BulkCatalog("id")
    # generate 200 000 columns
    for i in range(25):
        catalog.add_chunk(ChunkGroup({f"C{i}[{j}]" for j in range(8000)}, [f"path{i}"]))

    nb_r, cols = catalog.describe()
    assert nb_r == 0
    assert len(cols) == 200_000


def test_catalog_from_chunk_meta():
    record_root = storage_path_builder.record_path_level_0("r_id")
    base_path = storage_path_builder.session_path_level_1("r_id", "s_id")
    ch1 = generate_df(["A", "B"], [0, 1])
    ch2 = generate_df(["A", "B"], [2, 3, 4])
    ch3 = generate_df(["C"], [2, 3, 4])
    global_index = ch1.index.union(ch2.index).union(ch3.index)

    metas = [ChunkMeta.from_dataframe(df, base_path) for df in [ch1, ch2, ch3]]
    catalog = BulkCatalog.from_metas("r_id", metas, global_index=global_index)
    assert catalog.nb_rows == 5
    assert catalog.record_id == "r_id"
    assert catalog.all_columns == {"A", "B", "C"}
    assert catalog.chunk_count == 3
    assert catalog.all_columns_count == 3
    assert not catalog.is_columns_slide_only({"A"})
    assert not catalog.is_columns_slide_only({"B"})
    assert catalog.is_columns_slide_only({"C"})
    paths = set(catalog.get_chunk_paths())
    for m in metas:
        assert m.get_filepath(ChunkMeta.FileType.CHUNK, relative_to=record_root) in paths
    for p in paths:
        assert p.endswith("parquet")
    chunk_groups = catalog.filter_group_for_columns("B")
    assert len(chunk_groups) == 1
    assert chunk_groups[0].labels == {"A", "B"}
    assert len(set(chunk_groups[0].paths)) == 2

    chunk_groups = catalog.filter_group_for_columns("C")
    assert len(chunk_groups) == 1
    assert chunk_groups[0].labels == {"C"}
    assert len(set(chunk_groups[0].paths)) == 1

    chunk_groups = catalog.filter_group_for_columns(["C", "B"])
    assert len(chunk_groups) == 2
    assert {frozenset(c.labels) for c in chunk_groups} == {frozenset("AB"), frozenset("C")}
