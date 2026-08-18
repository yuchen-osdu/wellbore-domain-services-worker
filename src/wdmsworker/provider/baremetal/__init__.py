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
from concurrent.futures import ThreadPoolExecutor

from urllib.parse import urljoin
from osdu_baremetal.data_partition.data_partition_info import DataPartitionInfoGetter, DataPartitionInfo, BUCKET_KEY
from osdu_baremetal.storage.storage_baremetal import S3Storage
from osdu.core.api.storage.tenant import Tenant
import requests

PARTITION_SERVICE_URL_KEY = "SERVICE_URL_PARTITION"


class DataPartitionInfoGetterSync(DataPartitionInfoGetter):
    def get_partition_info(self, data_partition_id: str) -> DataPartitionInfo:
        if data_partition_info := self._cache.get(data_partition_id):
            return data_partition_info

        data_partition_url = urljoin(self._partition_host, f"partitions/{data_partition_id}")
        response = requests.get(data_partition_url)
        response.raise_for_status()
        data_partition_info = response.json()
        try:
            bucket = data_partition_info[BUCKET_KEY]["value"]
        except KeyError as e:
            raise KeyError(f"'{BUCKET_KEY}'are missing in Partition service") from e
        data_partition_info = DataPartitionInfo(bucket)
        self._cache[data_partition_id] = data_partition_info
        return data_partition_info


def get_tenant(data_partition_id: str) -> Tenant:
    partition_url = os.getenv(PARTITION_SERVICE_URL_KEY, "http://partition/api/partition/v1/")
    data_partition_info_getter = DataPartitionInfoGetterSync(partition_url)
    data_partition_info = data_partition_info_getter.get_partition_info(data_partition_id)

    return Tenant(data_partition_id=data_partition_id, project_id="", bucket_name=data_partition_info.bucket)


def initialize_provider(app):
    app.state.blob_storage = S3Storage()
    app.state.get_tenant = get_tenant
