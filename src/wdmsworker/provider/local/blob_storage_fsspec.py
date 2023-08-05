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

import io
from typing import Any, List
from os.path import join, normpath, relpath

try:
    import fsspec
except ImportError:
    raise ImportError("fsspec not installed, only needed here for development context")

from osdu.core.api.storage.blob import Blob
from osdu.core.api.storage.blob_storage_base import BlobStorageBase
from osdu.core.api.storage.exceptions import (
    with_blobstorage_exception,
    ResourceNotFoundException,
    AuthenticationException,
    ResourceExistsException,
)


class BlobStorageFsspec(BlobStorageBase):
    """
    BlobStorageBase over ffspec abstraction for local usage only
    """

    ExceptionMapping = {
        FileNotFoundError: ResourceNotFoundException,
        FileExistsError: ResourceExistsException,
        PermissionError: AuthenticationException,
    }

    def __init__(self, base_directory: str | None, protocol: str | None = None, **storage_options):
        self._base_directory = base_directory
        self._fs: fsspec.AbstractFileSystem = fsspec.filesystem(protocol or "file", **storage_options)
        self._protocol = protocol

    def _build_path(self, _tenant, object_name: str):
        base_path = self._base_directory
        if base_path:
            object_name = join(base_path, object_name)
        if self._protocol == "file":
            object_name = normpath(object_name)
            # don't replace volume - there's might be smarter way to do it ...
            object_name = object_name[:3] + object_name[3:].replace(":", "_")
        return object_name

    @with_blobstorage_exception(ExceptionMapping)
    async def delete(self, tenant, object_name: str, *, auth=None, params: dict | None = None, timeout: int = 10):
        full_path = self._build_path(tenant, object_name)
        self._fs.delete(full_path)

    @with_blobstorage_exception(ExceptionMapping)
    async def download(self, tenant, object_name: str, *, auth=None, timeout: int = 10, **kwargs) -> bytes:
        full_path = self._build_path(tenant, object_name)
        with self._fs.open(full_path, "rb") as file:
            return file.read()

    @with_blobstorage_exception(ExceptionMapping)
    async def download_metadata(self, tenant, object_name: str, *, auth=None, timeout: int = 10, **kwargs) -> Blob:
        # returns fake
        return Blob(
            identifier=object_name,
            name=object_name,
            bucket="",
            metadata={},
            acl=None,
            content_type=None,
            time_created=None,
            time_updated=None,
            size=0,
            etag=object_name,
        )

    @with_blobstorage_exception(ExceptionMapping)
    async def list_objects(
        self,
        tenant,
        *,
        auth=None,
        prefix: str = "",
        page_token: str | None = None,
        max_result: int | None = None,
        timeout: int = 10,
        **kwargs,
    ) -> List[str]:
        full_path = self._build_path(tenant, prefix)
        if full_path.endswith("/") or full_path.endswith("//") or self._fs.isdir(full_path):
            paths = [relpath(p, self._base_directory) for p in self._fs.ls(full_path)]
            return paths

        if self._fs.isfile(full_path):
            return [prefix]

        glob_result = [relpath(p, self._base_directory) for p in self._fs.glob(full_path + "*")]
        return glob_result

    @staticmethod
    def _preprocess_data(data: Any) -> bytes:  # -> bytes
        if isinstance(data, io.BufferedIOBase):
            return data.read()
        if isinstance(data, bytes):
            return data
        if isinstance(data, str):
            return data.encode()
        if isinstance(data, io.TextIOBase):
            return data.read().encode()
        if isinstance(data, io.IOBase):
            return data.read()

        raise TypeError(f'unsupported upload type: "{type(data)}"')

    @with_blobstorage_exception(ExceptionMapping)
    async def upload(
        self,
        tenant,
        object_name: str,
        file_data: Any,
        *,
        overwrite: bool = True,
        if_match=None,
        if_not_match=None,
        auth=None,
        content_type: str | None = None,
        metadata: dict | None = None,
        timeout: int = 30,
        **kwargs,
    ) -> Blob:
        full_path = self._build_path(tenant, object_name)
        data = self._preprocess_data(file_data)

        with self._fs.open(full_path, "wb") as file:
            file.write(data)

        return Blob(
            identifier=object_name,
            name=object_name,
            bucket="",
            metadata={},
            acl=None,
            content_type=None,
            time_created=None,
            time_updated=None,
            size=0,
            etag=object_name,
        )
