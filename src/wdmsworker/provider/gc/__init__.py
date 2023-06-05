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

from osdu_gcp.storage.blob_storage_gcp import GCloudAioStorage
from osdu.core.api.storage.tenant import Tenant


def initialize_provider(app):
    # TODO: must at least:
    #  - set in `app.state.blob_storage` a BlobStorageBase concrete instance
    #  - set in `app.state.get_tenant` a function taking one parameter `data_partition_id: str` that returns a `Tenant`
    #  note the following code has been inspired from what is done on WDMS side and MUST be reviewed:
    #      - https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/wellbore/wellbore-domain-services/-/blob/master/app/injector/gc_injector.py
    #      - https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/wellbore/wellbore-domain-services/-/blob/master/app/tenant/tenant_provider.py#L18

    _log_level_from_env = environ.get("LOG_LEVEL", "INFO")  # noqa: F841
    project_id_from_env = environ.get("OS_WELLBORE_DDMS_DATA_PROJECT_ID", "logstore-ibm")
    credentials_from_env = environ["OS_WELLBORE_DDMS_DATA_PROJECT_CREDENTIALS"]

    app.state.blob_storage = GCloudAioStorage()
    app.state.get_tenant = lambda data_partition_id: Tenant(
        data_partition_id=data_partition_id,
        project_id=project_id_from_env,
        credentials=credentials_from_env,
        bucket_name=f"{project_id_from_env}-logstore-osdu",
    )

    # TODO: review and setup log/traces accordingly upon needs
    raise NotImplementedError("gc initialization not implemented")
