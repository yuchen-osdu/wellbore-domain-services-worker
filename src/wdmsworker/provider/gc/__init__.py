# Copyright 2024 Google LLC
# Copyright 2024 EPAM Systems
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

import json
from os import environ
from urllib.parse import urljoin
from aiohttp import ClientSession

import requests
from osdu_gcp.data_partition.data_partition_info import (
    DataPartitionInfo,
    DataPartitionInfoGetter,
    GC_PROJECT_KEY,
    BUCKET_KEY,
)
from osdu_gcp.storage.blob_storage_gcp import GCloudAioStorage
from osdu.core.api.storage.tenant import Tenant

PARTITION_SERVICE_URL_KEY = "SERVICE_URL_PARTITION"
PROJECT_CREDENTIALS_KEY = "OS_WELLBORE_DDMS_DATA_PROJECT_CREDENTIALS"


class DataPartitionInfoGetterSync(DataPartitionInfoGetter):

    def get_partition_info(self, data_partition_id: str) -> DataPartitionInfo:
        if data_partition_info := self._cache.get(data_partition_id):
            return data_partition_info

        data_partition_url = urljoin(self._partition_url, f"partitions/{data_partition_id}")
        response = requests.get(data_partition_url)
        response.raise_for_status()
        data_partition_info = response.json()
        try:
            project_id = data_partition_info[GC_PROJECT_KEY]["value"]
            bucket = data_partition_info[BUCKET_KEY]["value"]
        except KeyError as e:
            raise KeyError(f"Either '{BUCKET_KEY}' or '{GC_PROJECT_KEY}' are missing in Partition service") from e
        data_partition_info = DataPartitionInfo(project_id, bucket)
        self._cache[data_partition_id] = data_partition_info
        return data_partition_info


def get_tenant(data_partition_id: str) -> Tenant:
    partition_url = environ.get(PARTITION_SERVICE_URL_KEY, "http://partition/api/partition/v1/")
    credentials_from_env = environ.get(PROJECT_CREDENTIALS_KEY)

    data_partition_info_getter = DataPartitionInfoGetterSync(partition_url)
    data_partition_info = data_partition_info_getter.get_partition_info(data_partition_id)

    return Tenant(
        data_partition_id=data_partition_id,
        project_id=data_partition_info.gc_project_id,
        credentials=credentials_from_env,
        bucket_name=data_partition_info.bucket,
    )


def initialize_provider(app):
    app.state.blob_storage = GCloudAioStorage(ClientSession(json_serialize=json.dumps))
    app.state.get_tenant = get_tenant
