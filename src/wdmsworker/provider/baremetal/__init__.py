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

import os

import asyncio
from osdu_baremetal.data_partition.data_partition_info import DataPartitionInfoGetter
from osdu_baremetal.storage.storage_baremetal import S3Storage
from osdu.core.api.storage.tenant import Tenant


PARTITION_SERVICE_URL_KEY = "SERVICE_URL_PARTITION"


def get_tenant(data_partition_id: str) -> Tenant:
    partition_url = os.getenv(
        PARTITION_SERVICE_URL_KEY, "http://partition/api/partition/v1/")

    data_partition_info_getter = DataPartitionInfoGetter(partition_url)
    data_partition_info = data_partition_info_getter.get_partition_info(
        data_partition_id)
    data_partition_info = asyncio.run(data_partition_info)
    return Tenant(
        data_partition_id=data_partition_id,
        project_id="",
        bucket_name=data_partition_info.bucket
    )

def initialize_provider(app):
    app.state.blob_storage = S3Storage()
    app.state.get_tenant = get_tenant
