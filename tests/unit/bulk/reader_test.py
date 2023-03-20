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

import asyncio
from io import BytesIO

# TODO [TAG pandas dependent]
import pandas as pd
from natsort import natsorted

from osdu.core.api.storage.blob_storage_base import BlobStorageBase

import pytest
from unittest.mock import AsyncMock, Mock

from pandas.testing import assert_frame_equal

from wdmsworker.bulk.dataframe import filter_by_index
from wdmsworker.model.filtering_model import BulkValueFilter
from ..generate_data import generate_df, generate_df_dtype

from wdmsworker.bulk.filtering import BulkValueFilterOperator, ValueFilters
from wdmsworker.bulk import storage_path_builder
from wdmsworker.bulk.storage_path_builder import join, is_a_chunk_file
from wdmsworker.bulk.catalog import BulkCatalog, BulkCatalogOrigin, ChunkGroup
from wdmsworker.bulk.read_errors import (
    TooManyColumnsRequested,
    TooManyValuesRequested,
    ReadBulkInvalidParameter,
    BulkCurvesNotFound,
)
from wdmsworker.bulk.reader import (
    read_bulk,
    read_bulk_outside_session,
    _forward_parquet,
    _build_response_from_df,
    _load_same_shape_dataframes_from_storage,
    _build_response_from_describe,
)
from wdmsworker.model.json_orient import JSONOrient
from wdmsworker.model.mime_types import MimeTypes, MimeType

format_params = [
    pytest.param(MimeTypes.PARQUET, None, id="parquet"),
    pytest.param(MimeTypes.JSON, JSONOrient.Split, id="json"),
]

describe_params = [False, True]


def assert_dataframe_from_content(expected_df, content, accept_type, orient):
    if accept_type == MimeTypes.PARQUET:
        actual_df = pd.read_parquet(BytesIO(content))
    else:
        actual_df = pd.read_json(content, orient=orient.value)
    assert_frame_equal(expected_df, actual_df, check_dtype=accept_type == MimeTypes.PARQUET)
    # check_dtype to False as json may lose strict type


def assert_describe_from_content(expected_df, response):
    assert response.mime_type == MimeTypes.JSON
    cols = str(list(expected_df.columns)).replace("'", '"')
    expected_content = f"{'{'}\"numberOfRows\":{len(expected_df.index)}, \"columns\":{cols}{'}'}"
    assert response.content == expected_content


async def assert_read_bulk(
    *,
    storage,
    tenant,
    catalog,
    accept_type,
    orient,
    expected_df,
    filters_params=None,
    offset=None,
    limit=None,
    columns=None,
    describe=False,
):
    # WHEN read full bulk
    response = await read_bulk(
        storage,
        tenant,
        catalog,
        accept_type,
        orient,
        offset=offset,
        limit=limit,
        curves_selection=columns,
        filters_params=filters_params,
        describe=describe,
    )

    # THEN
    # If in describe mode the result is always json
    if describe:
        assert_describe_from_content(expected_df, response)
    else:
        assert_dataframe_from_content(expected_df, response.content, accept_type, orient)


@pytest.mark.anyio
async def test_forward_parquet():
    storage_mock = Mock()
    storage_mock.download = AsyncMock(return_value=b"fake data")

    result = await _forward_parquet(storage_mock, Mock(), Mock())

    assert result.mime_type.type == "application/x-parquet"
    assert result.content == b"fake data"


def test_split_dataframe_iloc():
    df = generate_df(["A"], index=range(10))

    assert_frame_equal(df, filter_by_index(df))

    actual_df = filter_by_index(df, offset=2)
    assert_frame_equal(df.iloc[2:], actual_df)
    # just double check
    assert actual_df.shape == (8, 1)
    assert actual_df.index[0] == 2

    actual_df = filter_by_index(df, limit=5)
    assert_frame_equal(df.iloc[:5], actual_df)
    assert actual_df.shape == (5, 1)
    assert actual_df.index[0] == 0

    actual_df = filter_by_index(df, offset=2, limit=5)
    assert_frame_equal(df.iloc[2:7], actual_df)
    assert actual_df.shape == (5, 1)
    assert actual_df.index[0] == 2


@pytest.mark.anyio
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
async def test_build_response_df(accept_type: MimeType, orient: JSONOrient):
    columns = ["B", "C", "A"]
    df = generate_df(columns, index=range(6))

    result = await _build_response_from_df(df, accept_type, orient)
    assert accept_type == result.mime_type
    assert_dataframe_from_content(df, result.content, accept_type, orient)


@pytest.mark.anyio
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
async def test_build_response_big_df(accept_type: MimeType, orient: JSONOrient):
    columns = ["B", "C", "A"]

    df = generate_df(columns, index=range(350_000))
    result = await _build_response_from_df(df, accept_type, orient)
    assert accept_type == result.mime_type
    assert_dataframe_from_content(df, result.content, accept_type, orient)


@pytest.mark.anyio
@pytest.mark.parametrize("value_type", ["int", "float"])
async def test_load_same_shape_dataframes_from_storage_single(value_type):
    df = generate_df_dtype({"B": value_type, "C": value_type, "A": value_type}, index=range(6))
    storage_mock = Mock()

    storage_mock.download = AsyncMock(return_value=df.to_parquet(index=True))

    cmn_kwargs = {
        "storage": storage_mock,
        "tenant": Mock(),
        "obj_paths": [fake_chunk_name("parquet")],
    }
    actual_df = await _load_same_shape_dataframes_from_storage(**cmn_kwargs)
    assert_frame_equal(df, actual_df)

    assert_frame_equal(df[["A", "B"]], await _load_same_shape_dataframes_from_storage(**cmn_kwargs, columns=["A", "B"]))


@pytest.mark.anyio
@pytest.mark.parametrize("value_type", ["int", "float"])
async def test_load_same_shape_dataframes_from_storage_horizontal_slices(value_type):
    chunks = {
        fake_chunk_name("df1"): generate_df(["B", "C", "A"], index=range(6)),
        fake_chunk_name("df2"): generate_df(["B", "C", "A"], index=range(6, 10)),
        fake_chunk_name("df3"): generate_df(["B", "C", "A"], index=range(10, 14)),
    }

    df = pd.concat(chunks.values(), axis=0)
    storage_mock = Mock()

    async def download_mock(_tenant, path, *_args, **_kwargs):
        return chunks[path].to_parquet(index=True)

    storage_mock.download = download_mock

    cmn_kwargs = {"storage": storage_mock, "tenant": Mock(), "obj_paths": list(chunks.keys())}
    actual_df = await _load_same_shape_dataframes_from_storage(**cmn_kwargs)
    assert_frame_equal(df, actual_df)

    assert_frame_equal(df[["A", "B"]], await _load_same_shape_dataframes_from_storage(**cmn_kwargs, columns=["A", "B"]))


@pytest.mark.anyio
@pytest.mark.parametrize("data_type_name", ["int", "float", "date"])
async def test_generate_chunk_filename(data_type_name):
    # todo: add proper way to verify when values are negative,
    #  even it is partially tested by random data that can be negative
    cols = [f"{data_type_name}-{i}" for i in range(2)]
    df = generate_df(cols, index=range(10))
    df = df.set_index(cols[0])

    chunk_name = storage_path_builder.generate_chunk_filename(df) + ".parquet"
    assert is_a_chunk_file(chunk_name)


@pytest.mark.anyio
@pytest.mark.slow
@pytest.mark.perf
async def test_load_dataframe_from_storage_many_columns():
    cols = [f"c{i}" for i in range(10)]
    df = generate_df([f"c{i}" for i in range(10)], index=range(10))
    storage_mock = Mock()
    storage_mock.download = AsyncMock(return_value=df.to_parquet(index=True))
    chunk_name = storage_path_builder.generate_chunk_filename(df) + ".parquet"
    actual_df = await _load_same_shape_dataframes_from_storage(storage_mock, Mock(), [chunk_name])
    assert_frame_equal(df, actual_df)

    cols_requested = cols[2:]
    actual_df = await _load_same_shape_dataframes_from_storage(storage_mock, Mock(), [chunk_name], cols_requested)
    assert_frame_equal(df[cols_requested], actual_df)


@pytest.mark.anyio
async def test_unsupported_cases_raise():
    supported_format = MimeTypes.PARQUET

    # negative limit
    with pytest.raises(ReadBulkInvalidParameter):
        catalog = BulkCatalog("", origin=BulkCatalogOrigin.from_file())
        await read_bulk(AsyncMock(), Mock(), catalog, supported_format, None, limit=-1)


@pytest.mark.anyio
async def test_request_too_many_column_raise():
    catalog = BulkCatalog("", origin=BulkCatalogOrigin.generated_from_bulk())
    catalog.add_chunk(ChunkGroup({f"C[{i}]" for i in range(5001)}, ["path1"], []))
    args = [AsyncMock(), Mock(), catalog, MimeTypes.PARQUET, None]

    # read all
    with pytest.raises(TooManyColumnsRequested):
        await read_bulk(*args, curves_selection=None)

    # read 3000+ columns
    curve_selection = [f"C[{i}]" for i in range(1000, 4001)]
    with pytest.raises(TooManyColumnsRequested):
        await read_bulk(*args, curves_selection=curve_selection)

    # read 3000+ columns even with limit
    with pytest.raises(TooManyColumnsRequested):
        await read_bulk(*args, curves_selection=curve_selection, offset=10, limit=1)


@pytest.mark.anyio
async def test_request_too_many_values_raise():
    catalog = BulkCatalog("", origin=BulkCatalogOrigin.generated_from_bulk())
    catalog.add_chunk(ChunkGroup({f"C[{i}]" for i in range(100)}, ["path1"], []))
    catalog.nb_rows = 100_000_000
    args = [AsyncMock(), Mock(), catalog, MimeTypes.PARQUET, None]

    # request 6M
    with pytest.raises(TooManyValuesRequested):
        await read_bulk(*args, curves_selection=[f"C[{i}]" for i in range(6)])

    # request 4M but need to work on a 100M dataframe
    with pytest.raises(TooManyValuesRequested):
        await read_bulk(*args, limit=40_000)


@pytest.mark.anyio
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
async def test_single_chunk_case(bulk_storage_mock: BlobStorageBase, test_tenant, accept_type, orient):
    # GIVEN single chunk stored
    reference_df = generate_df(["A", "B", "C"], index=range(6))
    catalog = await store_chunks(bulk_storage_mock, test_tenant, [[reference_df]])
    catalog.nb_rows = len(reference_df.index)
    common_kwargs = {
        "storage": bulk_storage_mock,
        "tenant": test_tenant,
        "catalog": catalog,
        "accept_type": accept_type,
        "orient": orient,
    }

    # WHEN read full bulk
    await assert_read_bulk(**common_kwargs, expected_df=reference_df)
    await assert_read_bulk(**common_kwargs, expected_df=reference_df, columns=["A", "B", "C"])

    # WHEN read all columns, ensure column order
    await assert_read_bulk(**common_kwargs, expected_df=reference_df[["B", "A"]], columns=["B", "A"])

    # WHEN read one column
    await assert_read_bulk(**common_kwargs, expected_df=reference_df[["A"]], columns=["A"])

    # WHEN read few columns, offset, limit
    await assert_read_bulk(**common_kwargs, expected_df=reference_df[["A"]].iloc[1:3], columns=["A"], offset=1, limit=2)

    # WHEN offset is negative
    await assert_read_bulk(**common_kwargs, expected_df=reference_df[["A"]], columns=["A"], offset=-1)

    # WHEN limit exceed row count
    await assert_read_bulk(**common_kwargs, expected_df=reference_df[["A"]], columns=["A"], limit=1_000)
    await assert_read_bulk(
        **common_kwargs, expected_df=reference_df[["A"]].iloc[1:], columns=["A"], offset=1, limit=1_000
    )


@pytest.mark.anyio
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
async def test_single_chunk_case_filtering(bulk_storage_mock: BlobStorageBase, test_tenant, accept_type, orient):
    # GIVEN single chunk stored
    reference_df = generate_df(["A", "B", "C"], index=range(200))
    catalog = await store_chunks(bulk_storage_mock, test_tenant, [[reference_df]])
    catalog.nb_rows = len(reference_df.index)
    common_kwargs = {
        "storage": bulk_storage_mock,
        "tenant": test_tenant,
        "catalog": catalog,
        "accept_type": accept_type,
        "orient": orient,
    }

    bulk_filters = [
        BulkValueFilter(column="A", operator=BulkValueFilterOperator.Greater, value="350"),
        BulkValueFilter(column="A", operator=BulkValueFilterOperator.Less, value="850"),
        BulkValueFilter(column="C", operator=BulkValueFilterOperator.GreaterOrEqual, value="350"),
    ]
    expected_filtered_df = reference_df.loc[
        (reference_df["A"] > 350) & (reference_df["A"] < 850) & (reference_df["C"] >= 350)
    ]

    await assert_read_bulk(
        **common_kwargs,
        expected_df=expected_filtered_df,
        filters_params=ValueFilters(bulk_filters),
    )

    expected_filtered_df_with_filters = expected_filtered_df[20:50]

    await assert_read_bulk(
        **common_kwargs,
        expected_df=expected_filtered_df_with_filters,
        filters_params=ValueFilters(bulk_filters),
        offset=20,
        limit=30,
    )


@pytest.mark.anyio
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
async def test_single_chunk_case_many_columns(
    bulk_storage_mock: BlobStorageBase, test_tenant, accept_type, orient: JSONOrient
):
    cols = [f"c{i}" for i in range(510)]
    reference_df = generate_df(cols, index=range(6))
    catalog = await store_chunks(bulk_storage_mock, test_tenant, [[reference_df]])
    catalog.nb_rows = len(reference_df.index)
    common_kwargs = {
        "storage": bulk_storage_mock,
        "tenant": test_tenant,
        "catalog": catalog,
        "accept_type": accept_type,
        "orient": orient,
    }

    # WHEN read full bulk
    await assert_read_bulk(**common_kwargs, expected_df=reference_df)
    await assert_read_bulk(**common_kwargs, expected_df=reference_df, columns=cols)
    await assert_read_bulk(**common_kwargs, expected_df=reference_df[cols[2:]], columns=cols[2:])


@pytest.mark.anyio
@pytest.mark.parametrize("describe", describe_params)
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
@pytest.mark.parametrize(
    "chunk_method", ["no_split", "horizontal_and_vertical_split", "horizontal_split", "vertical_split"]
)
async def test_read_bulk(
    chunk_method, bulk_storage_mock: BlobStorageBase, test_tenant, describe, accept_type, orient: JSONOrient
):
    reference_df, chunk_groups = split_bulk_into_chunk(chunk_method)
    catalog = await store_chunks(bulk_storage_mock, test_tenant, chunk_groups)
    catalog.nb_rows = len(reference_df.index)
    common_kwargs = {
        "storage": bulk_storage_mock,
        "tenant": test_tenant,
        "catalog": catalog,
        "accept_type": accept_type,
        "orient": orient,
        "describe": describe,
    }
    await assert_read_multicases(assert_read_bulk, reference_df, **common_kwargs)


@pytest.mark.anyio
@pytest.mark.parametrize("describe", describe_params)
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
async def test_read_bulk_without_session(
    bulk_storage_mock: BlobStorageBase, test_tenant, describe, accept_type, orient: JSONOrient
):
    reference_df, chunk_groups = split_bulk_into_chunk("no_split")
    catalog = await store_chunks(
        bulk_storage_mock, test_tenant, chunk_groups, within_session=False, record_id="rid", bulk_id="bid"
    )
    catalog.nb_rows = len(reference_df.index)
    common_kwargs = {
        "storage": bulk_storage_mock,
        "tenant": test_tenant,
        "record_id": "rid",
        "bulk_id": "bid",
        "accept_type": accept_type,
        "orient": orient,
        "describe": describe,
    }
    await assert_read_multicases(assert_read_bulk_without_session, reference_df, **common_kwargs)


@pytest.mark.anyio
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
async def test_single_chunk_case_array(
    bulk_storage_mock: BlobStorageBase, test_tenant, accept_type, orient: JSONOrient
):
    # GIVEN df split into 4 chunks
    basic_cols = ["MD", "GR"]
    arrays_cols = [f"ARR[{i}]" for i in range(100)]
    cols = [*arrays_cols, *basic_cols]

    reference_df = generate_df(cols, index=range(10))
    catalog = await store_chunks(bulk_storage_mock, test_tenant, [[reference_df]])

    catalog.nb_rows = len(reference_df.index)
    common_kwargs = {
        "storage": bulk_storage_mock,
        "tenant": test_tenant,
        "catalog": catalog,
        "accept_type": accept_type,
        "orient": orient,
    }

    bulk_filters = [BulkValueFilter(column="MD", operator=BulkValueFilterOperator.GreaterOrEqual, value="500")]

    expected_df = reference_df[arrays_cols].loc[(reference_df["MD"] > 500)]
    await assert_read_bulk(
        **common_kwargs, columns=["ARR"], expected_df=expected_df, filters_params=ValueFilters(bulk_filters)
    )

    await assert_read_bulk(
        **common_kwargs,
        columns=[],
        expected_df=reference_df[natsorted(cols)].loc[(reference_df["MD"] >= 500)],
        filters_params=ValueFilters(bulk_filters),
    )


@pytest.mark.anyio
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
async def test_multi_chunk_case_array(bulk_storage_mock: BlobStorageBase, test_tenant, accept_type, orient: JSONOrient):
    # GIVEN df split into 4 chunks
    basic_cols = ["MD", "GR"]
    arrays_cols = [f"ARR[{i}]" for i in range(50)]
    cols = [*basic_cols, *arrays_cols]

    reference_df = generate_df(cols, index=range(100))
    catalog = await store_chunks(
        bulk_storage_mock,
        test_tenant,
        [
            [reference_df[[f"ARR[{i}]" for i in range(25, 45)]]],
            [reference_df[[f"ARR[{i}]" for i in range(45, 50)]]],
            [reference_df[[f"ARR[{i}]" for i in range(15)]]],
            [reference_df[[f"ARR[{i}]" for i in range(15, 25)]]],
            [reference_df[basic_cols]],
        ],
    )

    catalog.nb_rows = len(reference_df.index)
    common_kwargs = {
        "storage": bulk_storage_mock,
        "tenant": test_tenant,
        "catalog": catalog,
        "accept_type": accept_type,
        "orient": orient,
    }

    bulk_filters = [
        BulkValueFilter(column="MD", operator=BulkValueFilterOperator.GreaterOrEqual, value="500"),
    ]
    expected_full_array_df = reference_df[arrays_cols].loc[reference_df["MD"] >= 500]
    await assert_read_bulk(
        **common_kwargs,
        columns=["ARR"],
        expected_df=expected_full_array_df,
        filters_params=ValueFilters(bulk_filters),
    )

    await assert_read_bulk(
        **common_kwargs,
        columns=[],
        expected_df=reference_df[natsorted(cols)].loc[reference_df["MD"] >= 500],
        filters_params=ValueFilters(bulk_filters),
    )

    bulk_filters_gr = [
        BulkValueFilter(column="GR", operator=BulkValueFilterOperator.GreaterOrEqual, value="500"),
    ]
    expected_full_array_df_gr = reference_df[arrays_cols[16:27]].loc[reference_df["GR"] >= 500]
    await assert_read_bulk(
        **common_kwargs,
        columns=["ARR[16:26]"],
        expected_df=expected_full_array_df_gr,
        filters_params=ValueFilters(bulk_filters_gr),
    )


@pytest.mark.anyio
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
async def test_multi_chunk_case_filtering(
    bulk_storage_mock: BlobStorageBase, test_tenant, accept_type, orient: JSONOrient
):
    # GIVEN df split into 2 chunks
    reference_df = generate_df(["A", "B", "C", "D", "E"], index=range(100))
    catalog = await store_chunks(
        bulk_storage_mock, test_tenant, [[reference_df[["B", "C", "A"]]], [reference_df[["D", "E"]]]]
    )

    catalog.nb_rows = len(reference_df.index)
    common_kwargs = {
        "storage": bulk_storage_mock,
        "tenant": test_tenant,
        "catalog": catalog,
        "accept_type": accept_type,
        "orient": orient,
    }

    bulk_filters = [
        BulkValueFilter(column="E", operator=BulkValueFilterOperator.GreaterOrEqual, value="500"),
        BulkValueFilter(column="A", operator=BulkValueFilterOperator.Greater, value="350"),
        BulkValueFilter(column="B", operator=BulkValueFilterOperator.Less, value="850"),
    ]
    expected_df = reference_df[["B", "A"]].loc[
        (reference_df["A"] > 350) & (reference_df["B"] < 850) & (reference_df["E"] >= 500)
    ]
    await assert_read_bulk(
        **common_kwargs, columns=["B", "A"], expected_df=expected_df, filters_params=ValueFilters(bulk_filters)
    )

    bulk_filters_with_limits = [
        BulkValueFilter(column="A", operator=BulkValueFilterOperator.Greater, value="50"),
        BulkValueFilter(column="A", operator=BulkValueFilterOperator.Less, value="950"),
        BulkValueFilter(column="E", operator=BulkValueFilterOperator.GreaterOrEqual, value="100"),
    ]
    expected_df_with_limit = reference_df.loc[
        (reference_df["A"] > 50) & (reference_df["A"] < 950) & (reference_df["E"] >= 100)
    ][10:20]
    await assert_read_bulk(
        **common_kwargs,
        expected_df=expected_df_with_limit,
        filters_params=ValueFilters(bulk_filters_with_limits),
        offset=10,
        limit=10,
    )

    is_in_filter_values = [i for i in range(500, 600)]
    bulk_filters = [
        BulkValueFilter(column="A", operator=BulkValueFilterOperator.Greater, value="350"),
        BulkValueFilter(column="E", operator=BulkValueFilterOperator.In, value=is_in_filter_values),
    ]

    expected_df = reference_df[["A", "E"]].loc[
        (reference_df["A"] > 350) & (reference_df["E"].isin(is_in_filter_values))
    ]
    await assert_read_bulk(
        **common_kwargs, columns=["A", "E"], expected_df=expected_df, filters_params=ValueFilters(bulk_filters)
    )


@pytest.mark.anyio
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
async def test_multi_chunk_case_many_columns(
    bulk_storage_mock: BlobStorageBase, test_tenant, accept_type, orient: JSONOrient
):
    cols = [f"c{i}" for i in range(600)]
    reference_df = generate_df(cols, index=range(6))
    catalog = await store_chunks(
        bulk_storage_mock, test_tenant, [[reference_df[cols[:300]]], [reference_df[cols[300:]]]]
    )
    catalog.nb_rows = len(reference_df.index)
    common_kwargs = {
        "storage": bulk_storage_mock,
        "tenant": test_tenant,
        "catalog": catalog,
        "accept_type": accept_type,
        "orient": orient,
    }

    # WHEN read full bulk
    await assert_read_bulk(**common_kwargs, expected_df=reference_df)
    await assert_read_bulk(**common_kwargs, expected_df=reference_df, columns=cols)
    await assert_read_bulk(**common_kwargs, expected_df=reference_df[cols[2:]], columns=cols[2:])


@pytest.mark.anyio
@pytest.mark.parametrize(["accept_type", "orient"], format_params)
async def test_read_bulk_shifted_multi_chunk_case(
    bulk_storage_mock: BlobStorageBase, test_tenant, accept_type, orient: JSONOrient
):
    md_df = generate_df(["MD"], index=range(10))
    switched_gr_df = generate_df(["GR"], index=range(4, 10))
    switched_den_df = generate_df(["DEN"], index=range(6))
    index_df = pd.DataFrame(index=md_df.index)

    reference_df = pd.concat([index_df, md_df, switched_gr_df, switched_den_df], axis=1)

    catalog = await store_chunks(bulk_storage_mock, test_tenant, [[md_df], [switched_gr_df], [switched_den_df]])

    # storage index and update catalog
    catalog.index_path = storage_path_builder.join("_wdms_index_", "index.parquet")

    await bulk_storage_mock.upload(
        test_tenant,
        storage_path_builder.join(storage_path_builder.record_path_level_0(catalog.record_id), catalog.index_path),
        index_df.to_parquet(None, index=True),
    )

    catalog.nb_rows = len(reference_df.index)
    common_kwargs = {
        "storage": bulk_storage_mock,
        "tenant": test_tenant,
        "catalog": catalog,
        "accept_type": accept_type,
        "orient": orient,
    }

    # without offset/limit
    await assert_read_bulk(**common_kwargs, expected_df=reference_df[["MD"]], columns=["MD"])
    await assert_read_bulk(**common_kwargs, expected_df=reference_df[["GR"]], columns=["GR"])
    await assert_read_bulk(**common_kwargs, expected_df=reference_df[["DEN"]], columns=["DEN"])
    await assert_read_bulk(**common_kwargs, expected_df=reference_df[["MD", "DEN"]], columns=["MD", "DEN"])
    #
    # # with offset/limit
    await assert_read_bulk(
        **common_kwargs, expected_df=reference_df[["MD", "GR"]].iloc[2:6], columns=["MD", "GR"], offset=2, limit=4
    )
    await assert_read_bulk(
        **common_kwargs, expected_df=reference_df[["DEN"]].iloc[5:8], columns=["DEN"], offset=5, limit=3
    )
    await assert_read_bulk(
        **common_kwargs, expected_df=reference_df[["MD", "GR"]].iloc[5:], columns=["MD", "GR"], offset=5
    )


call_count = 0


@pytest.mark.anyio
async def test_load_dataframe_concurrency_is_limited():
    sync_event = asyncio.Event()
    data = pd.DataFrame().to_parquet(index=True)
    global call_count
    call_count = 0

    async def download_mock(*_, **__):
        global call_count
        call_count = call_count + 1
        await asyncio.wait_for(sync_event.wait(), 10)
        return data

    storage_mock = Mock()
    storage_mock.download = download_mock

    tasks = [
        asyncio.create_task(_load_same_shape_dataframes_from_storage(storage_mock, Mock(), [fake_chunk_name("pa")]))
        for _ in range(250)
    ]
    await asyncio.sleep(1)

    # only 100 download should been started
    assert call_count == 100

    # release them all
    sync_event.set()
    await asyncio.wait_for(asyncio.gather(*tasks), 10)

    # all completed
    assert call_count == 250


# ----------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------
# -------------------------------------------- TOOLING -----------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------


def fake_chunk_name(suffix):
    return "0000000000000000.0000000000000000." + suffix


def split_bulk_into_chunk(method: str):
    reference_df = generate_df(["A", "B", "C", "D", "E"], index=range(50))
    if method == "horizontal_and_vertical_split":
        return reference_df, [  # first level split by curve A, B, C
            [
                # second split by rows
                reference_df[["B", "C", "A"]].iloc[:9],
                reference_df[["B", "C", "A"]].iloc[9:],
            ],
            # first level split by curve D, E
            [
                # second split by rows
                reference_df[["E", "D"]].iloc[:6],
                reference_df[["E", "D"]].iloc[6:13],
                reference_df[["E", "D"]].iloc[13:],
            ],
        ]

    if method == "horizontal_split":
        return reference_df, [
            # cut horizontally, ie by rows
            [
                reference_df.iloc[:6],
                reference_df.iloc[6:13],
                reference_df.iloc[13:],
            ],
        ]

    if method == "vertical_split":
        return reference_df, [
            # split vertically, i e by curves
            [reference_df[["B", "C", "A"]]],
            [reference_df[["D", "E"]]],
        ]

    if method == "no_split":
        # no split at all
        return reference_df, [[reference_df]]

    raise ValueError()


async def store_chunks(
    storage: BlobStorageBase,
    tenant,
    chunks_groups,
    within_session=True,
    *,
    record_id="r_id",
    session_id="s_id",
    bulk_id="b_id",
) -> BulkCatalog:
    """ """
    catalog = BulkCatalog("r_id", origin=BulkCatalogOrigin.from_file())
    level_0_path = storage_path_builder.record_path_level_0(record_id)
    if within_session:
        relative_base_path = storage_path_builder.session_path_level_1(None, session_id)
    else:
        relative_base_path = storage_path_builder.bulk_path_level_1(None, bulk_id)

    for chunks in chunks_groups:
        chunk_paths = []
        columns = set()
        for df in chunks:
            chunk_relative_path = join(
                relative_base_path, storage_path_builder.generate_chunk_filename(df) + ".parquet"
            )
            chunk_full_path = join(level_0_path, chunk_relative_path)
            await storage.upload(tenant, chunk_full_path, df.to_parquet(None, index=True))
            chunk_paths.append(chunk_relative_path)
            columns.update(df.columns)

        catalog.add_chunk(ChunkGroup(columns, chunk_paths, []))
    return catalog


async def assert_read_bulk_without_session(
    *,
    storage,
    tenant,
    record_id,
    bulk_id,
    accept_type,
    orient,
    expected_df,
    offset=None,
    limit=None,
    columns=None,
    filters_params=None,
    describe=False,
):
    # WHEN read full bulk
    response = await read_bulk_outside_session(
        storage,
        tenant,
        record_id,
        bulk_id,
        accept_type,
        orient,
        offset=offset,
        limit=limit,
        curves_selection=columns,
        filters_params=filters_params,
        describe=describe,
    )

    # THEN
    # If in describe mode the result is always json
    if describe:
        assert_describe_from_content(expected_df, response)
    else:
        assert_dataframe_from_content(expected_df, response.content, accept_type, orient)


async def assert_read_multicases(assert_read_fn, reference_df, **common_kwargs):
    # WHEN reads in first chunk
    await assert_read_fn(**common_kwargs, expected_df=reference_df[["C", "B", "A"]], columns=["C", "B", "A"])
    await assert_read_fn(**common_kwargs, expected_df=reference_df[["A"]], columns=["A"])
    await assert_read_fn(**common_kwargs, expected_df=reference_df[["A"]].iloc[1:13], columns=["A"], offset=1, limit=12)

    # WHEN reads in second chunk
    await assert_read_fn(**common_kwargs, expected_df=reference_df[["E", "D"]], columns=["E", "D"])
    await assert_read_fn(**common_kwargs, expected_df=reference_df[["E"]], columns=["E"])
    await assert_read_fn(**common_kwargs, expected_df=reference_df[["D"]].iloc[1:13], columns=["D"], offset=1, limit=12)

    # WHEN reads in both chunks
    await assert_read_fn(**common_kwargs, expected_df=reference_df)
    await assert_read_fn(**common_kwargs, expected_df=reference_df, columns=list(reference_df.columns))
    await assert_read_fn(**common_kwargs, expected_df=reference_df[["E", "A"]], columns=["E", "A"])
    await assert_read_fn(
        **common_kwargs, expected_df=reference_df[["E", "A"]].iloc[1:13], columns=["E", "A"], offset=1, limit=12
    )

    # WHEN offset is negative
    await assert_read_fn(**common_kwargs, expected_df=reference_df[["E", "A"]], columns=["E", "A"], offset=-1)

    # WHEN limit exceed row count
    await assert_read_fn(**common_kwargs, expected_df=reference_df[["E", "A"]], columns=["E", "A"], limit=1_000)
    await assert_read_fn(
        **common_kwargs, expected_df=reference_df[["E", "A"]].iloc[1:], columns=["E", "A"], offset=1, limit=1_000
    )

    # WHEN asking no existing column
    with pytest.raises(BulkCurvesNotFound):
        await assert_read_fn(**common_kwargs, expected_df=None, columns=["Z"])

    bulk_filters = [
        BulkValueFilter(column="A", operator=BulkValueFilterOperator.Greater, value="150"),
        BulkValueFilter(column="A", operator=BulkValueFilterOperator.Less, value="950"),
        BulkValueFilter(column="C", operator=BulkValueFilterOperator.GreaterOrEqual, value="350"),
    ]
    requested_cols = ["B", "D", "C"]
    expected_filtered_df = reference_df.loc[
        (reference_df["A"] > 150) & (reference_df["A"] < 950) & (reference_df["C"] >= 350)
    ]

    # select columns, filter values only
    await assert_read_fn(
        **common_kwargs,
        expected_df=expected_filtered_df[requested_cols],
        columns=["B", "D", "C"],
        filters_params=ValueFilters(bulk_filters),
    )

    # select columns, filter values and index
    await assert_read_fn(
        **common_kwargs,
        expected_df=expected_filtered_df[requested_cols][2:5],
        columns=["B", "D", "C"],
        filters_params=ValueFilters(bulk_filters),
        offset=2,
        limit=3,
    )

    # no columns selected, filter values and index
    await assert_read_fn(
        **common_kwargs,
        expected_df=expected_filtered_df[2:5],
        filters_params=ValueFilters(bulk_filters),
        offset=2,
        limit=3,
    )


@pytest.mark.parametrize(
    "number_of_rows, columns, expected_str",
    [
        (None, None, '{"numberOfRows":null, "columns":null}'),
        (None, ["a", "b"], '{"numberOfRows":null, "columns":["a", "b"]}'),
        (5, None, '{"numberOfRows":5, "columns":null}'),
        (5, ["a", "b"], '{"numberOfRows":5, "columns":["a", "b"]}'),
    ],
)
def test_build_response_from_describe(number_of_rows, columns, expected_str):
    res = _build_response_from_describe(number_of_rows, columns)

    assert res.mime_type == MimeTypes.JSON
    assert res.content == expected_str
