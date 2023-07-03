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

from ..dependencies import blob_storage_dependency, tenant_dependency, content_type_dependency
from ..model.describe import DataframeBasicDescribe
from ..model.mime_types import MimeType
from . import writer
from . import write_errors as exc
from ..logger import get_logger


write_bulk_router = APIRouter()


WriteChunkResponse = DataframeBasicDescribe
""" Write response on post data within a session """


class WriteBulkResponse(BaseModel):
    """Write response on post data with no session"""

    bulkid: str
    describe: DataframeBasicDescribe


@write_bulk_router.post("/data/{record_id}/session/{session_id}")
async def post_bulk_chunk_in_session_route(
    record_id: str,
    session_id: str,
    request: Request,
    content_type: MimeType = Depends(content_type_dependency),
    storage=Depends(blob_storage_dependency),
    tenant=Depends(tenant_dependency),
) -> WriteChunkResponse:
    # TODO validation is incomplete
    try:
        return await writer.write_bulk_data_in_session(
            storage, tenant, await request.body(), content_type, record_id, session_id
        )
    except exc.BulkValidationError as e:
        get_logger().exception(f"validation error on write bulk for record {record_id}: {e}")
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))


@write_bulk_router.post("/data/{record_id}")
async def post_bulk_data_route(
    record_id: str,
    request: Request,
    reference: str | None = Query(default=None, description="name of the reference curve if any"),
    content_type: MimeType = Depends(content_type_dependency),
    storage=Depends(blob_storage_dependency),
    tenant=Depends(tenant_dependency),
) -> WriteBulkResponse:
    try:
        bulk_id, bulk_description = await writer.write_bulk(
            storage, tenant, await request.body(), content_type, record_id, reference
        )
    except exc.BulkUnprocessable as e:
        get_logger().error(f"error in post_bulk_data_route: {e}")
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    except exc.BulkValidationError as e:
        get_logger().error(f"Validation failure in post_bulk_data_route: {e}")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except exc.BulkUploadFailure as e:
        get_logger().exception(f"exception at upload data to blob storage {e}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR)

    return WriteBulkResponse.construct(bulkid=bulk_id, describe=bulk_description)


# TODO for now let consumer handle session part
# TODO only supports overwrite mode for now
@write_bulk_router.patch("/data/{record_id}/session/{session_id}")
async def session_complete_route(
    record_id: str,
    session_id: str,
    storage=Depends(blob_storage_dependency),
    tenant=Depends(tenant_dependency),
):
    from wdmsworker.bulk.catalog import get_chunks_metadata
    from wdmsworker.bulk.chunk_meta import find_conflicts

    # TODO check how it behaves with several thousands chunks
    metas = await get_chunks_metadata(storage, tenant, record_id, session_id)

    #
    conflicts = find_conflicts(metas)
    if conflicts:
        # TODO add conflicts supports
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "conflict found, not supported yet")

    # build index
    # chunks_meta_with_different_indexes = {meta.index_hash: meta for meta in metas}.values()
    # TODO limit gather

    raise NotImplementedError("session_complete_route")
