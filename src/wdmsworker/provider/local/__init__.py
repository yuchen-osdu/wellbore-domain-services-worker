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

from os import environ
import sys
import logging

from osdu.core.api.storage.tenant import Tenant
from .blob_storage_fsspec import BlobStorageFsspec
from ...constants import SERVICE_INTERNAL_NAME


def initialize_provider(app):
    local_folder = environ.get("USE_LOCALFS_BLOB_STORAGE_WITH_PATH")

    assert local_folder

    logger = logging.getLogger(SERVICE_INTERNAL_NAME)
    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    app.state.logger = logger
    app.state.blob_storage = BlobStorageFsspec(local_folder, "file", auto_mkdir=True)
    app.state.get_tenant = lambda dp: Tenant(data_partition_id=dp, project_id="", bucket_name="wdms-osdu")

    logger.info(f"local env initialized, blob storage => {local_folder}")
