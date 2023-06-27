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

from osdu_ibm.storage.blob_storage_ibm import IBMObjectStorage
from osdu.core.api.storage.tenant import Tenant


def initialize_provider(app):
    # TODO: must at least:
    #  - set in `app.state.blob_storage` a BlobStorageBase concrete instance
    #  - set in `app.state.get_tenant` a function taking one parameter `data_partition_id: str` that returns a `Tenant`
    #  note the following code has been inspired from what is done on WDMS side and MUST be reviewed:
    #      - https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/wellbore/wellbore-domain-services/-/blob/master/app/injector/ibm_injector.py
    #      - https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/wellbore/wellbore-domain-services/-/blob/master/app/tenant/tenant_provider.py#L18

    default_data_tenant_project_id = environ.get("OS_WELLBORE_DDMS_DATA_PROJECT_ID", "logstore-ibm")

    app.state.blob_storage = IBMObjectStorage()
    app.state.get_tenant = lambda data_partition_id: Tenant(
        data_partition_id=data_partition_id, project_id=default_data_tenant_project_id, bucket_name="logstore-osdu-ibm"
    )

    # TODO: review and setup log/traces accordingly upon needs
    raise NotImplementedError("ibm initialization not implemented")
