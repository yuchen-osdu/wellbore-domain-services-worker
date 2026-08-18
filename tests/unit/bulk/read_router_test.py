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
import contextlib
import json

import pandas as pd
import pytest
from fastapi import HTTPException
from unittest.mock import patch, AsyncMock, Mock

from wdmsworker.bulk.catalog import BulkCatalog, ChunkGroup
from wdmsworker.bulk.reader import ReadResult
from wdmsworker.bulk.read_router import get_bulk_route, _build_describe_response
from wdmsworker.model.mime_types import MimeTypes
from wdmsworker.bulk import errors as err


@pytest.fixture
def catalog() -> BulkCatalog:
    return BulkCatalog.from_single_dataframe(
        "record_id", "dir1/dir2/file.parquet", pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]}, index=[0, 1, 2])
    )


@contextlib.contextmanager
def path_catalog_storage(catalog_to_store):
    with patch(
        "wdmsworker.bulk.read_router.async_load_bulk_catalog_with_blob_storage",
        AsyncMock(return_value=catalog_to_store),
    ):
        yield


@pytest.fixture
def catalog_storage_mock(catalog):
    with patch(
        "wdmsworker.bulk.read_router.async_load_bulk_catalog_with_blob_storage", AsyncMock(return_value=catalog)
    ) as mock:
        yield mock


@pytest.fixture
def get_bulk_route_kwargs() -> dict:
    """provide all mocked kargs for get_bulk_route"""
    return {
        "record_id": "rid",
        "bulk_id": "bid",
        "offset": None,
        "limit": None,
        "curves": None,
        "describe": False,
        "bulk_filter_query": None,
        "accept_type": Mock(),
        "orient": Mock(),
        "storage": Mock(),
        "tenant": Mock(),
    }


@pytest.mark.anyio
async def test_get_bulk_route_forward_result_from_read(get_bulk_route_kwargs, catalog_storage_mock):
    with patch(
        "wdmsworker.bulk.read_router.reader.read_bulk",
        AsyncMock(return_value=ReadResult(content=b"content as bytes", mime_type=MimeTypes.PARQUET)),
    ):
        result = await get_bulk_route(**get_bulk_route_kwargs)

        assert result.status_code == 200
        assert MimeTypes.PARQUET.match(result.media_type)
        assert result.body == b"content as bytes"


@pytest.mark.anyio
@pytest.mark.parametrize("curves_selection", [None, "A,B", "B,A", "B"])
async def test_get_bulk_route_simple_describe(get_bulk_route_kwargs, catalog_storage_mock, curves_selection):
    params = dict(**get_bulk_route_kwargs)
    params["describe"] = True
    if curves_selection is not None:
        params["curves"] = curves_selection
    result = await get_bulk_route(**params)

    assert result.status_code == 200
    assert MimeTypes.JSON.match(result.media_type)

    result_json = json.loads(result.body)
    assert result_json["numberOfRows"] == 3
    expected_columns = curves_selection.split(",") if curves_selection is not None else ["A", "B"]
    assert result_json["columns"] == expected_columns


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error,expected_code",
    [
        (err.CurvesNotFoundError(), 404),
        (err.TooManyColumnsError(100, 10), 413),
        (err.TooManyValuesError(100, 10), 413),
        (err.InvalidParameterError(), 400),
        (err.BulkCaseNotSupportedError(), 412),
    ],
)
async def test_get_bulk_route_error_vs_status_code(error, expected_code, get_bulk_route_kwargs, catalog_storage_mock):
    with patch("wdmsworker.bulk.read_router.reader.read_bulk", AsyncMock(side_effect=error)):
        with pytest.raises(HTTPException) as e:
            response = await get_bulk_route(**get_bulk_route_kwargs)
            # either it raises directly an HTTPException or construct a response with an error status so check both
            assert response.status_code == expected_code
            raise HTTPException(status_code=response.status_code)

        exc = e.value
        assert exc.status_code == expected_code


@pytest.mark.anyio
async def test_read_too_large_response_contains_curves_partitions(get_bulk_route_kwargs):
    catalog = BulkCatalog("rid", 4)
    catalog.add_chunk(ChunkGroup({"A", "B", "C[1]"}, ["f1"]))
    catalog.add_chunk(ChunkGroup({"D[6]", "D[8]", "D[5]", "D[7]"}, ["f2"]))
    catalog.add_chunk(ChunkGroup({"F[700]", "F[699]", "E[1]", "E[8]", "E[7]"}, ["f3"]))
    with path_catalog_storage(catalog):
        with patch(
            "wdmsworker.bulk.read_router.reader.read_bulk", AsyncMock(side_effect=err.TooManyColumnsError(100, 10))
        ):
            response = await get_bulk_route(**get_bulk_route_kwargs)
            assert response.status_code == 413
            response_obj = json.loads(response.body)
            assert response_obj["bulkDescription"]["totalNumberOfRows"] == catalog.nb_rows
            assert response_obj["bulkDescription"]["totalNumberOfColumns"] == catalog.nb_columns
            curves_set = [set(p["curves"]) for p in response_obj["bulkDescription"]["partitions"]]
            assert response_obj["errorType"] == "READ_REQUEST_TOO_LARGE"
            assert response_obj["limits"]["values"] == 10_000_000
            assert response_obj["limits"]["columns"] == 3_000
            assert curves_set == [{"A", "B", "C[1]"}, {"D[5:8]"}, {"E[1]", "F[699:700]", "E[8]", "E[7]"}]


@pytest.mark.anyio
async def test_get_bulk_route_error_vs_load_catalog(get_bulk_route_kwargs, catalog_storage_mock):
    catalog_storage_mock.side_effect = ValueError("fake error")
    with pytest.raises(HTTPException) as e:
        await get_bulk_route(**get_bulk_route_kwargs)

    exc = e.value
    assert exc.status_code == 500
    assert "fake error" in exc.detail


@pytest.mark.parametrize("number_of_rows, columns", [(None, None), (None, ["a", "b"]), (5, None), (5, ["a", "b"])])
def test_build_describe_response(number_of_rows, columns):
    # Test the construction of the response
    result = _build_describe_response(number_of_rows, columns)

    assert result.media_type == MimeTypes.JSON.type
    result_json = json.loads(result.body)

    assert result_json["numberOfRows"] == number_of_rows
    assert result_json["columns"] == columns
