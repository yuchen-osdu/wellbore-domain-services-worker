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

import json

import pandas as pd
import pytest
from fastapi import HTTPException
from unittest.mock import patch, AsyncMock, Mock

from wdmsworker.bulk.catalog import BulkCatalog
from wdmsworker.bulk.reader import ReadResult
from wdmsworker.bulk.read_router import get_bulk_route, _build_describe_response
from wdmsworker.model.mime_types import MimeTypes
from wdmsworker.bulk import read_errors as err


@pytest.fixture
def catalog() -> BulkCatalog:
    return BulkCatalog.from_single_dataframe(
        "record_id", "dir1/dir2/file.parquet", pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]}, index=[0, 1, 2])
    )


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
        (err.BulkCurvesNotFound(), 404),
        (err.TooManyColumnsRequested(100, 10), 413),
        (err.TooManyValuesRequested(100, 10), 413),
        (err.ReadBulkInvalidParameter(), 400),
        (err.ReadBulkCaseNotSupportedException(), 412),
    ],
)
async def test_get_bulk_route_error_vs_status_code(error, expected_code, get_bulk_route_kwargs, catalog_storage_mock):
    with patch("wdmsworker.bulk.read_router.reader.read_bulk", AsyncMock(side_effect=error)):
        with pytest.raises(HTTPException) as e:
            await get_bulk_route(**get_bulk_route_kwargs)

        exc = e.value
        assert exc.status_code == expected_code


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error,expected_code",
    [
        (err.BulkCurvesNotFound(), 404),
        (err.TooManyColumnsRequested(100, 10), 413),
        (err.TooManyValuesRequested(100, 10), 413),
        (err.ReadBulkInvalidParameter(), 400),
        (err.ReadBulkCaseNotSupportedException(), 412),
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
