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

import pytest
from fastapi import HTTPException
from unittest.mock import patch, AsyncMock
from wdmsworker.bulk.errors import (
    BulkValidationError,
    TooManyColumnsError,
    TooManyValuesError,
    TooManyConflictsToResolve,
)
from wdmsworker.bulk.write_router import post_bulk_chunk_in_session_route, post_bulk_data_route, session_complete_route


@pytest.mark.anyio
async def test_post_bulk_chunk_in_session_route_use_writer():
    # not sure if this test actually make sens
    with patch("wdmsworker.bulk.write_router.writer.write_bulk_data_in_session", AsyncMock()) as mock:
        await post_bulk_chunk_in_session_route("rid", "sid", AsyncMock(), AsyncMock(), AsyncMock())

        mock.assert_called_once()


@pytest.mark.anyio
async def test_post_bulk_chunk_in_session_route_bulk_validation_is_a_422():
    with patch(
        "wdmsworker.bulk.write_router.writer.write_bulk_data_in_session",
        AsyncMock(side_effect=BulkValidationError("fake validation error")),
    ):
        with pytest.raises(HTTPException) as e:
            await post_bulk_chunk_in_session_route("rid", "sid", AsyncMock(), AsyncMock(), AsyncMock())
        actual_exc = e.value
        assert actual_exc.status_code == 422
        assert "fake validation error" in actual_exc.detail


@pytest.mark.anyio
@pytest.mark.parametrize("exception_cls", [TooManyValuesError, TooManyColumnsError])
async def test_post_bulk_chunk_in_session_content_too_large(exception_cls):
    with patch(
        "wdmsworker.bulk.write_router.writer.write_bulk_data_in_session",
        AsyncMock(side_effect=exception_cls(1337, 42)),
    ):
        response = await post_bulk_chunk_in_session_route("rid", "sid", AsyncMock(), AsyncMock(), AsyncMock())
        assert response.status_code == 413


@pytest.mark.anyio
@pytest.mark.parametrize("exception_cls", [TooManyValuesError, TooManyColumnsError])
async def test_post_bulk_content_too_large(exception_cls):
    with patch(
        "wdmsworker.bulk.write_router.writer.write_bulk",
        AsyncMock(side_effect=exception_cls(1337, 42)),
    ):
        response = await post_bulk_data_route("rid", AsyncMock(), None, AsyncMock(), AsyncMock(), AsyncMock())
        assert response.status_code == 413


@pytest.mark.anyio
async def test_complete_sessions_too_many_conflicts():
    with patch(
        "wdmsworker.bulk.write_router.writer.complete_session",
        AsyncMock(side_effect=TooManyConflictsToResolve("Nop")),
    ):
        with pytest.raises(HTTPException) as e:
            await session_complete_route("rid", "sid", AsyncMock(), AsyncMock(), AsyncMock())

        assert e.value.status_code == 413
