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
import hashlib
import uuid
import random
from typing import List, Literal
import json
from io import BytesIO

import pandas as pd
import pytest
from unittest.mock import patch, AsyncMock, Mock
from natsort import natsorted

from osdu.core.api.storage.blob_storage_base import BlobStorageBase

from wdmsworker.bulk import storage_path_builder
from wdmsworker.bulk.catalog import async_load_bulk_catalog_with_blob_storage
from wdmsworker.bulk.chunk_meta import ChunkMeta
from wdmsworker.bulk.errors import *
from wdmsworker.model.json_orient import JSONOrient
from wdmsworker.model.mime_types import MimeTypes, MimeType
from wdmsworker.bulk.dataframe import dump_df, dump_to_parquet
from wdmsworker.bulk.writer import write_bulk, write_bulk_data_in_session, complete_session
from wdmsworker.bulk.read_router import get_bulk_route
from wdmsworker.bulk.dataframe import load_df

from ..generate_data import generate_df, assert_frame_equal, assert_dataframe_from_content

format_params = [
    pytest.param(MimeTypes.PARQUET, id="parquet"),
    pytest.param(MimeTypes.JSON, id="json"),
]


@pytest.fixture
def record_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def session_id() -> str:
    return str(uuid.uuid4())


@pytest.mark.anyio
async def test_write_chunk(bulk_storage_mock: BlobStorageBase, test_tenant, record_id: str, session_id: str):
    content_type = MimeTypes.PARQUET
    chunk1_df = generate_df(["GR", "floatA[1]", "floatA[0]"], index=range(6))
    chunk1_df["MD"] = list(range(3, 9))

    df_desc = await write_bulk_data_in_session(
        bulk_storage_mock, test_tenant, dump_df(chunk1_df, content_type), content_type, record_id, session_id
    )
    assert df_desc.rowCount == 6
    assert df_desc.curves == {"MD": 1, "GR": 1, "floatA": 2}
    assert df_desc.reference.start_end_values()[0] == 0
    assert df_desc.reference.start_end_values()[1] == 5

    chunk2_df = generate_df(["floatA[2]", "floatA[3]"], index=range(1, 4))

    df_desc = await write_bulk_data_in_session(
        bulk_storage_mock, test_tenant, dump_df(chunk2_df, content_type), content_type, record_id, session_id
    )
    assert df_desc.rowCount == 3
    assert df_desc.curves == {"floatA": 2}
    assert df_desc.reference.start_end_values()[0] == 1
    assert df_desc.reference.start_end_values()[1] == 3

    # for now just check pieces are there in storage
    for ch in (chunk1_df, chunk2_df):
        base_path = storage_path_builder.join(
            storage_path_builder.session_path_level_1(record_id, session_id), ChunkMeta.generate_filename(ch)
        )

        chunk_parquet = await bulk_storage_mock.download(test_tenant, base_path + ".parquet")
        chunk_meta_bytes = await bulk_storage_mock.download(test_tenant, base_path + ".meta")

        chunk_meta = ChunkMeta.load(base_path, chunk_meta_bytes)
        assert set(chunk_meta.columns) == set(ch.columns)
        assert [chunk_meta.index.start, chunk_meta.index.end] == ch.iloc[[0, -1]].index.values.tolist()
        assert chunk_meta.nb_rows == len(ch)
        assert_dataframe_from_content(ch, chunk_parquet, content_type)


@pytest.mark.anyio
@pytest.mark.parametrize("content_type", format_params)
@pytest.mark.parametrize("with_ref", [True, False])
async def test_write_bulk(bulk_storage_mock: BlobStorageBase, test_tenant, content_type: MimeType, with_ref: bool):
    reference_df = generate_df(["floatB", "floatA[1]", "floatA[0]"], index=range(6))
    reference_df["MD"] = list(range(3, 9))
    record_id = str(uuid.uuid4())

    bulk_id, descr = await write_bulk(
        bulk_storage_mock,
        test_tenant,
        dump_df(reference_df, content_type),
        content_type,
        record_id,
        "MD" if with_ref else None,
    )

    # check output
    assert bulk_id is not None
    assert descr.rowCount == len(reference_df)
    df_column_desc = descr.reference.start_end_df()
    expected_column_desc = reference_df.iloc[[0, -1]].copy()
    expected_column_desc["_wdms_index_"] = expected_column_desc.index
    expected_column_desc = expected_column_desc[["MD" if with_ref else "_wdms_index_"]]

    pd.testing.assert_frame_equal(expected_column_desc, df_column_desc)

    # then catalog just be there
    catalog = await async_load_bulk_catalog_with_blob_storage(bulk_storage_mock, test_tenant, record_id, bulk_id)
    assert catalog.record_id == record_id
    assert catalog.nb_rows == len(reference_df)
    assert catalog.chunk_count == 1
    assert catalog.all_columns == set(reference_df.columns)

    base_chunk_path = storage_path_builder.record_path_level_0(record_id)
    full_chunk_path = storage_path_builder.join(base_chunk_path, list(catalog.get_chunk_paths())[0])
    content = await bulk_storage_mock.download(test_tenant, full_chunk_path)
    stored_df = load_df(content, MimeTypes.PARQUET)
    assert_frame_equal(reference_df, stored_df)


@pytest.mark.anyio
@pytest.mark.parametrize("content_type", format_params)
async def test_write_bulk_validation_failure_reserved_named(
    bulk_storage_mock: BlobStorageBase, test_tenant, content_type: MimeType
):
    reference_df = generate_df(["__index_level_1__"], index=range(6))
    with pytest.raises(BulkValidationError):
        await write_bulk(bulk_storage_mock, test_tenant, dump_df(reference_df, content_type), content_type, "record_id")


@pytest.mark.anyio
async def test_write_bulk_raise_unprocessable_data():
    content_type = MimeTypes.JSON
    reference_df = generate_df(["A", "V"], index=range(6))
    with patch("wdmsworker.bulk.writer.load_df", Mock(side_effect=Exception("Test"))):
        with pytest.raises(BulkUnprocessableError):
            await write_bulk(AsyncMock(), Mock(), dump_df(reference_df, content_type), content_type, "record_id")

    with pytest.raises(BulkUnprocessableError):
        await write_bulk(AsyncMock(), Mock(), b"invalid parquet", MimeTypes.PARQUET, "record_id")


@pytest.mark.anyio
@pytest.mark.parametrize("content_type", format_params)
@pytest.mark.parametrize(
    "index",
    [
        pytest.param(["a", "b"], id="non_numerical"),
        pytest.param([0, 1, 1], id="non_unique"),
    ],
)
async def test_write_bulk_validation_failure_bad_index(
    bulk_storage_mock: BlobStorageBase, test_tenant, content_type: MimeType, index
):
    reference_df = generate_df(["A"], index=index)
    with pytest.raises(BulkValidationError):
        await write_bulk(bulk_storage_mock, test_tenant, dump_df(reference_df, content_type), content_type, "record_id")


@pytest.mark.anyio
async def test_write_upload_failure_raise_an_error(bulk_storage_mock: BlobStorageBase, test_tenant):
    with patch.object(bulk_storage_mock, "upload", AsyncMock(side_effect=Exception("Test"))):
        with pytest.raises(BulkUploadError):
            await write_bulk(
                bulk_storage_mock,
                test_tenant,
                dump_df(generate_df(["A"], index=[1, 2]), MimeTypes.JSON),
                MimeTypes.JSON,
                "record_id",
            )


@pytest.mark.anyio
async def test_write_too_many_columns():
    content = dump_df(generate_df([str(i) for i in range(3001)], index=[0]), MimeTypes.PARQUET)
    with pytest.raises(TooManyColumnsError):
        await write_bulk(AsyncMock(), Mock(), content, MimeTypes.PARQUET, "rid")

    with pytest.raises(TooManyColumnsError):
        await write_bulk_data_in_session(AsyncMock(), Mock(), content, MimeTypes.PARQUET, "rid", "sid")


@pytest.mark.anyio
async def test_write_too_many_values():
    content = dump_df(generate_df([str(i) for i in range(100)], index=range(100001)), MimeTypes.PARQUET)
    with pytest.raises(TooManyValuesError):
        await write_bulk(Mock(), Mock(), content, MimeTypes.PARQUET, "rid")

    with pytest.raises(TooManyValuesError):
        await write_bulk_data_in_session(Mock(), Mock(), content, MimeTypes.PARQUET, "rid", "sid")


@pytest.mark.anyio
@pytest.mark.parametrize("column_split", [True, False], ids=["vsplit", ""])
# if True bulk will be split three times along columns
@pytest.mark.parametrize("row_split", [True, False], ids=["hsplit", ""])
# if True chunks will be split in two along rows
@pytest.mark.parametrize(
    "use_reference,set_reference_in_chunk",
    [(True, True), (True, False), (False, False)],
    ids=["with_ref", "partial_ref", "without_ref"],
)
# flags to set the reference_curve when calling commit_session and/or write_chunk
@pytest.mark.parametrize("delete_chunk_index", [True, False], ids=["chunk_index_deletion", ""])
# if True, will random deletes some index and/or reference dataframe associated to some chunks. Session commit should
# complete successfully without it, the drawback should only be a less efficient commit
async def test_commit_session_overwrite_no_conflict(
    bulk_storage_mock: BlobStorageBase,
    test_tenant,
    record_id,
    session_id,
    column_split: bool,
    row_split: bool,
    use_reference: bool,
    set_reference_in_chunk: bool,
    delete_chunk_index: bool,
):
    df = generate_df(["A", "B[0]", "B[1]", "C", "D"], index=[4, 5, 6, 7, 8, 9])
    df["MD"] = [0.5, 1.6, 2.2, 2.3, 5, 5.1]

    #
    bulk_id, describe = await commit_chunks(
        bulk_storage_mock,
        test_tenant,
        record_id,
        session_id,
        df,
        column_split,
        row_split,
        reference="MD" if use_reference else None,
        delete_chunk_index="random" if delete_chunk_index else "none",
    )

    assert bulk_id
    assert describe.curves == {"MD": 1, "A": 1, "B": 2, "C": 1, "D": 1}
    assert describe.rowCount == 6
    if use_reference:
        assert describe.reference.name == "MD"
        assert "float" in describe.reference.dataType
        assert describe.reference.start_end_values() == [0.5, 5.1]
    else:
        assert describe.reference.start_end_values() == [4, 9]

    assert not describe.reference.hasNan
    assert not describe.reference.hasDuplicate
    assert describe.reference.monotonicity == "increasing"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "chunks, error_expected",
    [
        # ref smaller inside case => NOK
        ([generate_df(["A", "B"], index=range(5)), pd.DataFrame({"MD": [0.5, 1.0, 1.5]}, index=range(3))], True),
        # ref smaller but half inside, half outside => NOK
        ([generate_df(["A", "B"], index=range(5)), pd.DataFrame({"MD": [0.5, 1.0, 1.5]}, index=range(4, 7))], True),
        # ref smaller and outside => NOK
        ([generate_df(["A", "B"], index=range(5)), pd.DataFrame({"MD": [0.5, 1.0, 1.5]}, index=range(7, 10))], True),
        # ref same index => OK
        ([generate_df(["A", "B"], index=range(3)), pd.DataFrame({"MD": [0.5, 1.0, 1.5]}, index=range(3))], False),
        # ref same index, other chunks horizontal sliced => OK
        (
            [
                generate_df(["A", "B"], index=range(3)),
                generate_df(["A", "B"], index=range(3, 5)),
                pd.DataFrame({"MD": [0.5, 1.0, 1.5, 2.0, 2.5]}, index=range(5)),
            ],
            False,
        ),
        # ref same index, ref horizontally sliced => OK
        (
            [
                generate_df(["A", "B"], index=range(5)),
                pd.DataFrame({"MD": [0.5, 1.0, 1.5]}, index=range(3)),
                pd.DataFrame({"MD": [2.0, 2.5]}, index=range(3, 5)),
            ],
            False,
        ),
        # ref same index, both horizontally sliced
        (
            [
                generate_df(["A"], index=range(2)),
                generate_df(["A"], index=range(2, 6)),
                generate_df(["B"], index=range(3)),
                generate_df(["B"], index=range(3, 6)),
                pd.DataFrame({"MD": [0.5, 1.0, 1.5, 2.0]}, index=range(4)),
                pd.DataFrame({"MD": [2.5, 3.0]}, index=range(4, 6)),
            ],
            False,
        ),
        # ref bigger index
        (
            [
                generate_df(["A"], index=range(2, 6)),
                generate_df(["B"], index=range(3, 6)),
                pd.DataFrame({"MD": [0.5, 1.0, 1.5, 2.0]}, index=range(4)),
                pd.DataFrame({"MD": [2.5, 3.0]}, index=range(4, 6)),
            ],
            False,
        ),
    ],
    ids=[
        "ref smaller inside",
        "ref smaller but half inside, half outside",
        "ref smaller and outside",
        "ref same index",
        "ref same index, other chunks horizontal sliced",
        "ref same index, ref horizontally sliced",
        "ref same index, both horizontally sliced",
        "ref bigger index",
    ],
)
async def test_commit_reference_coverage(
    bulk_storage_mock: BlobStorageBase, test_tenant, record_id, session_id, chunks, error_expected
):
    commit_task = commit_chunks(
        bulk_storage_mock,
        test_tenant,
        record_id,
        session_id,
        chunks,
        False,
        False,
        reference="MD",
    )
    if error_expected:
        with pytest.raises(BulkValidationError):
            await commit_task
    else:
        await commit_task


@pytest.mark.anyio
@pytest.mark.parametrize("column_split", [True, False], ids=["vsplit", "no_vsplit"])
# if True bulk will be split three times along columns
@pytest.mark.parametrize("row_split", [True, False], ids=["hsplit", "no_hsplit"])
@pytest.mark.parametrize(
    "use_reference,set_reference_in_chunk",
    [(True, True), (True, False), (False, False)],
    ids=["with_ref", "partial_ref", "without_ref"],
)
# flags to set the reference_curve when calling commit_session and/or write_chunk
@pytest.mark.parametrize("delete_chunk_index", [True, False], ids=["chunk_index_deletion", ""])
# if True, will random deletes some index and/or reference dataframe associated to some chunks. Session commit should
# complete successfully without it, the drawback should only be a less efficient commit
@pytest.mark.parametrize("simulate_previous_with_dask", [True, False], ids=["previous_is_dask", "previous_is_wrk"])
async def test_commit_session_update_no_conflict(
    bulk_storage_mock: BlobStorageBase,
    test_tenant,
    record_id,
    session_id,
    column_split: bool,
    row_split: bool,
    use_reference: bool,
    set_reference_in_chunk: bool,
    delete_chunk_index: bool,
    simulate_previous_with_dask: bool,
):
    # push data other different column
    previous_df = generate_df(["Y", "Z"], index=[4, 5, 6, 7])
    previous_bulk_id, _ = await commit_chunks(
        bulk_storage_mock,
        test_tenant,
        record_id,
        None,
        previous_df,
        column_split,
        row_split,
        reference=None,
        delete_chunk_index="all" if delete_chunk_index else "none",
        delete_single_bulk_meta=delete_chunk_index,
        force_session_single_chunk=False,
        simulate_dask_impl=simulate_previous_with_dask,
    )

    df = generate_df(["A", "B[0]", "B[1]", "C", "D"], index=[4, 5, 6, 7, 8, 9])
    df["MD"] = [0.5, 1.6, 2.2, 2.3, 5, 5.1]

    bulk_id, describe = await commit_chunks(
        bulk_storage_mock,
        test_tenant,
        record_id,
        session_id,
        df,
        column_split,
        row_split,
        reference="MD" if use_reference else None,
        delete_chunk_index="random" if delete_chunk_index else "none",
        commit_mode="update",
        previous_bulk_id=previous_bulk_id,
    )

    assert bulk_id
    assert describe.curves == {"MD": 1, "A": 1, "B": 2, "C": 1, "D": 1, "Y": 1, "Z": 1}
    assert describe.rowCount == 6
    if use_reference:
        assert describe.reference.name == "MD"
        assert "float" in describe.reference.dataType
        assert describe.reference.start_end_values() == [0.5, 5.1]
    else:
        assert describe.reference.start_end_values() == [4, 9]

    assert not describe.reference.hasNan
    assert not describe.reference.hasDuplicate
    assert describe.reference.monotonicity == "increasing"

    expected_df = df.join(previous_df)
    await read_all_and_validate(bulk_storage_mock, test_tenant, record_id, bulk_id, expected_df)


@pytest.mark.anyio
async def test_commit_session_update_no_conflict_after_conflict(
    bulk_storage_mock: BlobStorageBase,
    test_tenant,
    record_id,
    session_id,
):
    # push data other different column
    previous_df = generate_df(["Y", "Z"], index=range(15))
    previous_bulk_id, _ = await commit_chunks(
        bulk_storage_mock,
        test_tenant,
        record_id,
        None,
        previous_df,
        False,
        True,
        reference=None,
        simulate_dask_impl=True,
        simulate_dask_conflict_resolve=True,
    )

    df = generate_df(["A", "B[0]", "B[1]", "C", "D"], index=[4, 5, 6, 7, 8, 9])

    bulk_id, describe = await commit_chunks(
        bulk_storage_mock,
        test_tenant,
        record_id,
        session_id,
        df,
        False,
        False,
        None,
        commit_mode="update",
        previous_bulk_id=previous_bulk_id,
    )

    assert bulk_id
    assert describe.curves == {"A": 1, "B": 2, "C": 1, "D": 1, "Y": 1, "Z": 1}
    assert describe.rowCount == 15
    assert describe.reference.start_end_values() == [0, 14]

    assert not describe.reference.hasNan
    assert not describe.reference.hasDuplicate
    assert describe.reference.monotonicity == "increasing"

    expected_df = previous_df.join(df)
    expected_df = expected_df[natsorted(expected_df.columns.to_list())]
    await read_all_and_validate(bulk_storage_mock, test_tenant, record_id, bulk_id, expected_df)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "use_reference,set_reference_in_chunk",
    [(True, True), (True, False), (False, False)],
    ids=["with_ref", "partial_ref", "without_ref"],
)
# flags to set the reference_curve when calling commit_session and/or write_chunk
@pytest.mark.parametrize("delete_chunk_index", [True, False], ids=["chunk_index_deletion", ""])
# if True, will random deletes some index and/or reference dataframe associated to some chunks. Session commit should
# complete successfully without it, the drawback should only be a less efficient commit
async def test_commit_session_overwrite_with_conflict(
    bulk_storage_mock: BlobStorageBase,
    test_tenant,
    record_id,
    session_id,
    use_reference: bool,
    set_reference_in_chunk: bool,
    delete_chunk_index: bool,
):
    df = pd.DataFrame({c: [c] * 6 for c in ["a", "b", "c", "d", "e", "f"]})
    df["MD"] = list(range(5, 5 + 6))

    chunks = [
        # 3 first chunks on columns "a" and "b" conflicts due to column misalignment
        pd.DataFrame({c: [c] * 4 for c in ["a", "b"]}, index=[0, 1, 2, 3]),
        pd.DataFrame({c: [c] * 2 for c in ["a"]}, index=[4, 5]),
        pd.DataFrame({c: [c] * 2 for c in ["b"]}, index=[4, 5]),
        # 5 next chunks on columns c, d, e conflicts by index overlaps and misalignment
        pd.DataFrame({c: [c] * 4 for c in ["c", "d"]}, index=[0, 1, 2, 3]),
        pd.DataFrame({c: [c] * 4 for c in ["c", "d"]}, index=[2, 3, 4, 5]),
        pd.DataFrame({c: [c] * 2 for c in ["c", "e"]}, index=[4, 5]),
        pd.DataFrame({c: [c] * 2 for c in ["d"]}, index=[4, 5]),
        pd.DataFrame({c: [c] * 4 for c in ["e"]}, index=[0, 1, 2, 3]),
        # no conflicts on the 2 last ones
        pd.DataFrame({"MD": [5, 6, 7], "f": ["f"] * 3}, index=[0, 1, 2]),
        pd.DataFrame({"MD": [8, 9, 10], "f": ["f"] * 3}, index=[3, 4, 5]),
    ]
    #
    bulk_id, describe = await commit_chunks(
        bulk_storage_mock,
        test_tenant,
        record_id,
        session_id,
        chunks,
        False,
        False,
        reference="MD" if use_reference else None,
        delete_chunk_index="random" if delete_chunk_index else "none",
    )

    assert bulk_id
    assert describe.curves == {"MD": 1, "a": 1, "b": 1, "c": 1, "d": 1, "e": 1, "f": 1}
    assert describe.rowCount == 6
    if use_reference:
        assert describe.reference.name == "MD"
        assert "int" in describe.reference.dataType
        assert describe.reference.start_end_values() == [5, 10]
    else:
        assert describe.reference.start_end_values() == [0, 5]

    assert not describe.reference.hasNan
    assert not describe.reference.hasDuplicate
    assert describe.reference.monotonicity == "increasing"

    actual_df = await read_all(bulk_storage_mock, test_tenant, record_id, bulk_id)
    assert set(actual_df.columns.tolist()) == set(df.columns.tolist())
    actual_df = actual_df[df.columns.tolist()]
    pd.testing.assert_frame_equal(actual_df, df)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "use_reference,set_reference_in_chunk",
    [(True, True), (True, False), (False, False)],
    ids=["with_ref", "partial_ref", "without_ref"],
)
# flags to set the reference_curve when calling commit_session and/or write_chunk
@pytest.mark.parametrize("delete_chunk_index", [True, False], ids=["chunk_index_deletion", ""])
# if True, will random deletes some index and/or reference dataframe associated to some chunks. Session commit should
# complete successfully without it, the drawback should only be a less efficient commit
@pytest.mark.parametrize("simulate_previous_with_dask", [True, False], ids=["previous_is_dask", "previous_is_wrk"])
@pytest.mark.parametrize("row_split", [True, False], ids=["hsplit", "no_hsplit"])
async def test_commit_session_update_with_conflict(
    bulk_storage_mock: BlobStorageBase,
    test_tenant,
    record_id,
    session_id,
    use_reference: bool,
    set_reference_in_chunk: bool,
    delete_chunk_index: bool,
    simulate_previous_with_dask: bool,
    row_split: bool,
):
    # push data other different column
    previous_df = pd.DataFrame({c: ["previous"] * 4 for c in ["a", "b"]}, index=[4, 5, 6, 7])
    previous_df["MD"] = [9.0, 10.0, 11.0, 12.0]
    previous_bulk_id, _ = await commit_chunks(
        bulk_storage_mock,
        test_tenant,
        record_id,
        None,
        previous_df,
        False,
        row_split,
        reference=None,
        delete_chunk_index="all" if delete_chunk_index else "none",
        delete_single_bulk_meta=delete_chunk_index,
        force_session_single_chunk=False,
        simulate_dask_impl=simulate_previous_with_dask,
    )

    df = pd.DataFrame({c: [c] * 6 for c in ["a", "b", "c", "d", "e", "f"]})
    df["MD"] = [float(i) for i in range(5, 5 + 6)]

    chunks = [
        # 3 first chunks on columns "a" and "b" conflicts due to column misalignment
        pd.DataFrame({c: [c] * 4 for c in ["a", "b"]}, index=[0, 1, 2, 3]),
        pd.DataFrame({c: [c] * 2 for c in ["a"]}, index=[4, 5]),
        pd.DataFrame({c: [c] * 2 for c in ["b"]}, index=[4, 5]),
        # 5 next chunks on columns c, d, e conflicts by index overlaps and misalignment
        pd.DataFrame({c: [c] * 4 for c in ["c", "d"]}, index=[0, 1, 2, 3]),
        pd.DataFrame({c: [c] * 4 for c in ["c", "d"]}, index=[2, 3, 4, 5]),
        pd.DataFrame({c: [c] * 2 for c in ["c", "e"]}, index=[4, 5]),
        pd.DataFrame({c: [c] * 2 for c in ["d"]}, index=[4, 5]),
        pd.DataFrame({c: [c] * 4 for c in ["e"]}, index=[0, 1, 2, 3]),
        # no conflicts on the 2 last ones but will with previous
        pd.DataFrame({"MD": [5.0, 6.0, 7.0], "f": ["f"] * 3}, index=[0, 1, 2]),
        pd.DataFrame({"MD": [8.0, 9.0, 10.0], "f": ["f"] * 3}, index=[3, 4, 5]),
    ]

    bulk_id, describe = await commit_chunks(
        bulk_storage_mock,
        test_tenant,
        record_id,
        session_id,
        chunks,
        False,
        False,
        reference="MD" if use_reference else None,
        delete_chunk_index="random" if delete_chunk_index else "none",
        commit_mode="update",
        previous_bulk_id=previous_bulk_id,
    )

    assert bulk_id
    assert describe.curves == {"MD": 1, "a": 1, "b": 1, "c": 1, "d": 1, "e": 1, "f": 1}
    assert describe.rowCount == 8

    if use_reference:
        assert describe.reference.name == "MD"
        assert describe.reference.start_end_values() == [5, 12]
    else:
        assert describe.reference.start_end_values() == [0, 7]

    assert not describe.reference.hasNan
    assert not describe.reference.hasDuplicate
    assert describe.reference.monotonicity == "increasing"

    expected_df = df.combine_first(previous_df)
    actual_df = await read_all(bulk_storage_mock, test_tenant, record_id, bulk_id)
    assert set(actual_df.columns.tolist()) == set(expected_df.columns.tolist())
    actual_df = actual_df[expected_df.columns.tolist()]
    pd.testing.assert_frame_equal(actual_df, expected_df)


# ----------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------
# -------------------------------------------- TOOLING -----------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------


async def read_all(storage: BlobStorageBase, tenant, record_id: str, bulk_id: str) -> pd.DataFrame:
    response = await get_bulk_route(
        record_id, bulk_id, None, None, None, None, None, MimeTypes.PARQUET, JSONOrient.Split, storage, tenant
    )
    return pd.read_parquet(BytesIO(response.body))


async def read_all_and_validate(
    storage: BlobStorageBase, tenant, record_id: str, bulk_id: str, expected_df: pd.DataFrame
):
    actual_df = await read_all(storage, tenant, record_id, bulk_id)
    assert_frame_equal(actual_df, expected_df)


def generate_chunk_filename_dask_impl(dataframe: pd.DataFrame) -> str:
    import time

    first_idx, last_idx = dataframe.index[0], dataframe.index[-1]
    if isinstance(dataframe.index, pd.DatetimeIndex):
        first_idx, last_idx = dataframe.index[0].value, dataframe.index[-1].value

    shape_str = "_".join(f"{cn}:{dt}" for cn, dt in dataframe.dtypes.items())
    shape = hashlib.sha1(shape_str.encode()).hexdigest()
    cur_time = round(time.time() * 1000)
    return f"{first_idx}_{last_idx}_{cur_time}.{shape}"


async def simulate_dask_commit(
    storage: BlobStorageBase,
    tenant,
    record_id: str,
    session_id: str,
    chunks: List[pd.DataFrame],
    global_index: pd.Index,
    force_session_single_chunk: bool,
    as_conflicted: bool,
) -> str:
    bulk_id = str(uuid.uuid4())
    root_bulk_dir = storage_path_builder.bulk_path_level_1(record_id, bulk_id)
    root_session = storage_path_builder.session_path_level_1(record_id, session_id)

    # case of single chunk if store without session requested
    if len(chunks) == 1 and not force_session_single_chunk:
        # no catalog, single parquet file only
        ch = chunks[0]
        ch.index.name = "_wdms_index_"
        ch_parquet = ch.to_parquet()
        filename = generate_chunk_filename_dask_impl(ch)
        await storage.upload(
            tenant,
            storage_path_builder.join(root_bulk_dir, f"{filename}.parquet"),
            ch_parquet,
        )

        return bulk_id

    # algo and construction come from wdms code
    # create meta and chunk parquets
    chunk_name_by_shape = {}

    conflicted_dir = str(uuid.uuid4()) + ".parquet"

    for i, ch in enumerate(chunks):
        ch.index.name = "_wdms_index_"
        ch_parquet = ch.to_parquet()
        if as_conflicted:
            # simulate conflict storage, several chunk inside a folder part.0, part,1 ...
            await storage.upload(
                tenant, storage_path_builder.join(root_bulk_dir, conflicted_dir, f"part.{i}.parquet"), ch_parquet
            )
        else:
            filename = generate_chunk_filename_dask_impl(ch)
            await storage.upload(tenant, storage_path_builder.join(root_session, f"{filename}.parquet"), ch_parquet)

            meta_content = json.dumps(
                {
                    "columns": list(ch.columns),
                    "dtypes": [str(dt) for dt in ch.dtypes],
                    "nb_rows": len(ch.index),
                    "index_hash": hashlib.sha1(ch.index.values).hexdigest(),
                }
            ).encode()

            # later for catalog construction
            chunk_name_by_shape.setdefault(hashlib.sha1(".".join(sorted(ch.columns)).encode()).hexdigest(), []).append(
                (ch, filename)
            )
            await storage.upload(tenant, storage_path_builder.join(root_session, f"{filename}.meta"), meta_content)

    # upload index
    await storage.upload(
        tenant,
        storage_path_builder.join(root_bulk_dir, "_wdms_index_", "index.parquet"),
        pd.DataFrame(index=global_index).to_parquet(),
    )

    # construct and upload catalog
    columns = []
    if as_conflicted:
        # in that case, only a single dir path is put inside the catalog, not one path per chunk
        columns.append(
            {
                "labels": list(chunks[0].columns),  # all chunk have same column, take the first one then
                "paths": [storage_path_builder.join("bulk", bulk_id, "data", conflicted_dir)],
                "dtypes": [],
            }
        )
    else:
        for v in chunk_name_by_shape.values():
            columns.append(
                {
                    "labels": list(v[0][0].columns),  # all chunk have same column, take the first one then
                    "paths": [storage_path_builder.join("session", session_id, "data", f"{t[1]}.parquet") for t in v],
                    "dtypes": [],
                }
            )

    catalog_dict = {
        "recordId": record_id,
        "nbRows": len(global_index),
        "indexPath": storage_path_builder.join("bulk", bulk_id, "data", "_wdms_index_", "index.parquet"),
        "columns": columns,
    }

    await storage.upload(
        tenant,
        storage_path_builder.join(storage_path_builder.bulk_path_level_1(record_id, bulk_id), "bulk_catalog.json"),
        json.dumps(catalog_dict).encode(),
    )

    return bulk_id


@pytest.mark.anyio
async def test_try_simulate_dask_commit(
    # async def try_simulate_dask_commit(
    bulk_storage_mock: BlobStorageBase,
    test_tenant,
    record_id,
    session_id,
):
    chunks = [
        generate_df(["MD", "X"], range(5)),
        generate_df(["MD", "X"], range(5, 10)),
        generate_df(["MD", "X"], range(10, 15)),
        # generate_df(["Y"], range(15)),
        # generate_df(["Z"], range(15)),
    ]
    g_index = chunks[0].index
    bulk_id = await simulate_dask_commit(
        bulk_storage_mock, test_tenant, record_id, session_id, chunks, g_index, False, True
    )
    print("simulated chunks storage with Dask impl for ", record_id, "bulkd_id:", bulk_id)


def split_dataframe(df: pd.DataFrame, column_split: bool, row_split: bool, shuffle: bool = True) -> List[pd.DataFrame]:
    v_split = []
    if column_split and len(df.columns) > 1:
        columns = df.columns
        if len(columns) > 4:
            v_split.append(df[columns[:2]])
            v_split.append(df[columns[2:3]])
            v_split.append(df[columns[3:]])
        else:
            v_split.append(df[columns[:1]])
            v_split.append(df[columns[1:]])
    else:
        v_split.append(df)

    if row_split:
        chunks = []
        for v_df in v_split:
            chunks.append(v_df.iloc[:2])
            chunks.append(v_df.iloc[2:])
    else:
        chunks = v_split

    if shuffle:
        random.shuffle(chunks)

    return chunks


async def commit_chunks(
    storage: BlobStorageBase,
    tenant,
    record_id,
    session_id,
    df_or_chunks: pd.DataFrame | List[pd.DataFrame],
    column_split: bool,
    row_split: bool,
    reference: str | None,
    delete_chunk_index: Literal["none", "random", "all"] | str = "none",
    delete_single_bulk_meta: bool = False,
    commit_mode: str = "overwrite",
    previous_bulk_id: str | None = None,
    force_session_single_chunk: bool = True,
    simulate_dask_impl: bool = False,
    simulate_dask_conflict_resolve: bool = False,
):
    if isinstance(df_or_chunks, list):
        # passing list of already split chunks is not compatible with dask storage simulation
        assert not (simulate_dask_impl or simulate_dask_conflict_resolve or column_split or row_split)
        chunks = df_or_chunks
    else:
        chunks = split_dataframe(df_or_chunks, column_split, row_split, shuffle=not simulate_dask_conflict_resolve)
    session_id = session_id or str(uuid.uuid4())[-8:]

    if simulate_dask_impl or simulate_dask_conflict_resolve:
        bulk_id = await simulate_dask_commit(
            storage,
            tenant,
            record_id,
            session_id,
            chunks,
            df_or_chunks.index,
            force_session_single_chunk,
            simulate_dask_conflict_resolve,
        )
        return bulk_id, None

    use_session = len(chunks) > 1 or force_session_single_chunk
    result = None

    if use_session:
        for ch in chunks:
            await write_bulk_data_in_session(
                storage,
                tenant,
                dump_to_parquet(ch),
                MimeTypes.PARQUET,
                record_id,
                session_id,
                reference_curve=reference,
            )
    else:
        result = await write_bulk(storage, tenant, dump_to_parquet(chunks[0]), MimeTypes.PARQUET, record_id, reference)

    if use_session:
        root_dir = storage_path_builder.session_path_level_1(record_id, session_id)
    else:
        root_dir = storage_path_builder.bulk_path_level_1(record_id, result[0])
    all_objs = await storage.list_objects(tenant, prefix=root_dir)
    assert len(all_objs) >= len(chunks)

    if delete_chunk_index != "none":
        # pseudo simulate, failure or not presence of either index and or ref dataframe for some chunks
        # session commit must still be able to complete successfully, but less efficiently
        list_objs = [p for p in all_objs if "index." in p or "MD." in p]
        for p in list_objs:
            if delete_chunk_index == "all" or random.randint(0, 1):
                await storage.delete(tenant, p)

    if not use_session and delete_single_bulk_meta:
        # pseudo simulate, failure or not presence of meta
        list_objs = [p for p in all_objs if p.endswith(".meta")]
        assert len(list_objs) < 2  # it's only possible for write without session, maximum one meta file
        for p in list_objs:
            await storage.delete(tenant, p)
    #
    if use_session:
        result = await complete_session(
            storage,
            tenant,
            record_id,
            session_id,
            commit_mode,
            reference_curve=reference,
            previous_bulk=previous_bulk_id,
        )

    return result
