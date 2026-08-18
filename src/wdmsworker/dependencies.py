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

from uuid import uuid4
from fastapi import Request, Header, Depends, Query
from osdu.core.api.storage.blob_storage_base import BlobStorageBase

from .model.json_orient import JSONOrient
from .model.mime_types import MimeTypes, MimeType


async def correlation_id_dependency(request: Request) -> str:
    """
    :param request:
    :return: return correlation id from request header or generates one
    """
    return request.headers.get("correlation-id", str(uuid4()))


async def data_partition_dependency(data_partition: str = Header(alias="data-partition-id")) -> str:
    return data_partition


async def content_type_dependency(
    content_type: str | None = Header(default=None, alias="Content-Type"),
) -> MimeType | None:
    try:
        if content_type is not None:
            return MimeTypes.from_str(content_type)
    except ValueError:
        pass
    return None


async def accept_dependency(accept: str | None = Header(default=None, alias="Accept")) -> MimeType | None:
    try:
        if accept is not None:
            return MimeTypes.from_str(accept)
    except ValueError:
        pass
    return None


async def json_orient_dependency(
    orient: JSONOrient = Query(JSONOrient.Split, description="format for JSON only."),
) -> JSONOrient:
    return orient


async def blob_storage_dependency(request: Request) -> BlobStorageBase:
    return request.app.state.blob_storage


async def tenant_dependency(request: Request, dp: str = Depends(data_partition_dependency)):
    return request.app.state.get_tenant(dp)
