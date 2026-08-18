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

import pytest
from io import BytesIO, StringIO

from osdu.core.api.storage.exceptions import ResourceNotFoundException
from wdmsworker.provider.local.blob_storage_fsspec import BlobStorageFsspec
from osdu.core.api.storage.tenant import Tenant


@pytest.fixture
def blob_storage(tmp_path):
    return BlobStorageFsspec(base_directory=str(tmp_path), protocol="file", auto_mkdir=True)


@pytest.fixture
def test_tenant():
    return Tenant(data_partition_id="dp", project_id="prj", credentials=None, bucket_name="b")


@pytest.mark.anyio
async def test_blob_storage_fsspec_all_in_one(blob_storage: BlobStorageFsspec, test_tenant):
    object_name = "test_obj"

    blob = await blob_storage.upload(test_tenant, object_name, BytesIO(b"test object content"))
    assert blob.name == object_name

    content = await blob_storage.download(test_tenant, object_name)
    assert content == b"test object content"

    meta = await blob_storage.download_metadata(test_tenant, object_name)
    assert meta.name == object_name

    await blob_storage.delete(test_tenant, object_name)

    with pytest.raises(ResourceNotFoundException):
        await blob_storage.download(test_tenant, object_name)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "actual,expected",
    [
        (BytesIO(b"content"), b"content"),
        (b"content", b"content"),
        ("content", b"content"),
        (StringIO("content"), b"content"),
    ],
    ids=["bytesIO", "bytes", "string", "stringIO"],
)
async def test_blob_storage_fsspec_all_in_one(blob_storage: BlobStorageFsspec, test_tenant, actual, expected):
    object_name = str(uuid.uuid4())

    await blob_storage.upload(test_tenant, object_name, actual)
    content = await blob_storage.download(test_tenant, object_name)
    assert content == expected
