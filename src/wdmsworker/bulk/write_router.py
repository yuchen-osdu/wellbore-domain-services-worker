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

from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from pydantic import BaseModel

from ..capture_timings import capture_timings
from ..dependencies import blob_storage_dependency, tenant_dependency, content_type_dependency
from ..model.describe import DataframeBasicDescribe
from ..model.error_model import ErrorWithTypeResponse, LimitExceededErrorResponse, to_json_response
from ..model.mime_types import MimeType
from . import writer
from . import errors as exc
from ..logger import get_logger

write_bulk_router = APIRouter()


WriteChunkResponse = DataframeBasicDescribe
""" Write response on post data within a session """


class WriteBulkResponse(BaseModel):
    """Write response on post data with no session"""

    bulkid: str
    describe: DataframeBasicDescribe


@write_bulk_router.post(
    "/data/{record_id}/session/{session_id}",
    response_model=WriteChunkResponse,
    responses={
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "invalid content"},
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: {
            "description": "the content size exceeds the limit.",
            "model": LimitExceededErrorResponse,
        },
    },
)
async def post_bulk_chunk_in_session_route(
    record_id: str,
    session_id: str,
    request: Request,
    reference: str | None = Query(default=None, description="name of the reference curve if any"),
    content_type: MimeType = Depends(content_type_dependency),
    storage=Depends(blob_storage_dependency),
    tenant=Depends(tenant_dependency),
):
    try:
        return await writer.write_bulk_data_in_session(
            storage, tenant, await request.body(), content_type, record_id, session_id, reference_curve=reference
        )
    except (exc.BulkValidationError, exc.BulkUnprocessableError) as e:
        get_logger().exception(f"validation error on write bulk for record {record_id}: {e}")
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    except (exc.TooManyValuesError, exc.TooManyColumnsError) as e:
        get_logger().error(f"too bug dataframe posted: {e}")
        # TODO this might actually be done/solved here, better be strict for now ...
        return to_json_response(
            LimitExceededErrorResponse.from_exception(e, additional_description="Data chunk too large"),
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )


@write_bulk_router.post(
    "/data/{record_id}",
    response_model=WriteBulkResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "bad request"},
        status.HTTP_404_NOT_FOUND: {"description": "resource not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "invalid content"},
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: {
            "description": "the content size exceeds the limit.",
            "model": LimitExceededErrorResponse,
        },
    },
)
async def post_bulk_data_route(
    record_id: str,
    request: Request,
    reference: str | None = Query(default=None, description="name of the reference curve if any"),
    content_type: MimeType = Depends(content_type_dependency),
    storage=Depends(blob_storage_dependency),
    tenant=Depends(tenant_dependency),
):
    try:
        bulk_id, bulk_description = await writer.write_bulk(
            storage, tenant, await request.body(), content_type, record_id, reference
        )
    except exc.BulkUnprocessableError as e:
        get_logger().error(f"error in post_bulk_data_route: {e}")
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    except exc.BulkValidationError as e:
        get_logger().error(f"Validation failure in post_bulk_data_route: {e}")
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    except (exc.TooManyValuesError, exc.TooManyColumnsError) as e:
        get_logger().error(f"too bug dataframe posted: {e}")
        # TODO this might actually be done/solved here, better be strict for now ...
        return to_json_response(
            LimitExceededErrorResponse.from_exception(
                e, additional_description="Bulk data is too large and must be split into smaller chunks"
            ),
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    except exc.BulkUploadError as e:
        get_logger().exception(f"exception at upload data to blob storage {e}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR)

    return WriteBulkResponse.model_construct(bulkid=bulk_id, describe=bulk_description)


# TODO only supports overwrite commit mode for now
@write_bulk_router.patch("/data/{record_id}/session/{session_id}")
@capture_timings("PATCH /data/{record_id}/session/{session_id}")
async def session_complete_route(
    record_id: str,
    session_id: str,
    completion: writer.SessionCompletionMode = Query(...),
    reference: str | None = Query(default=None, description="name of the reference curve if any"),
    from_bulk: str | None = Query(default=None, description="previous bulk id for commit update"),
    storage=Depends(blob_storage_dependency),
    tenant=Depends(tenant_dependency),
):
    if completion == writer.SessionCompletionMode.Abandon:
        # TODO delete chunks
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED)

    try:
        bulk_id, bulk_description = await writer.complete_session(
            storage, tenant, record_id, session_id, completion, from_bulk, reference
        )
        return WriteBulkResponse.model_construct(bulkid=bulk_id, describe=bulk_description)
    except exc.TooManyConflictsToResolve as e:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(e))
    except exc.BulkCommitNoDataError as e:
        return to_json_response(
            ErrorWithTypeResponse(errorType=e.errorType, message=e.description),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except (exc.BulkCommitError, exc.BulkValidationError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
