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
from osdu.core.api.storage.tenant import Tenant

from wdmsworker.provider.local import BlobStorageFsspec


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def test_tenant():
    return Tenant(data_partition_id="dp", project_id="p", credentials=None, bucket_name="b")


@pytest.fixture
async def local_blob_path(tmp_path_factory):
    return str(tmp_path_factory.mktemp(basename="blob-"))


@pytest.fixture
async def bulk_storage_mock(tmp_path_factory):
    local_blob_path = str(tmp_path_factory.mktemp(basename="blob-"))
    return BlobStorageFsspec(local_blob_path, "file", auto_mkdir=True)
