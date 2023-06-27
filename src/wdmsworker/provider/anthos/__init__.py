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

from osdu_anthos.storage.storage_anthos import AnthosStorage
from osdu.core.api.storage.tenant import Tenant


def initialize_provider(app):
    # TODO: must at least:
    #  - set in `app.state.blob_storage` a BlobStorageBase concrete instance
    #  - set in `app.state.get_tenant` a function taking one parameter `data_partition_id: str` that returns a `Tenant`
    #  note the following code has been inspired from what is done on WDMS side and MUST be reviewed:
    #      - https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/wellbore/wellbore-domain-services/-/blob/master/app/injector/anthos_injector.py
    #      - https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/wellbore/wellbore-domain-services/-/blob/master/app/tenant/tenant_provider.py#L18

    app.state.blob_storage = AnthosStorage()
    app.state.get_tenant = lambda data_partition_id: Tenant(
        data_partition_id=data_partition_id, project_id="undefined", bucket_name="logstore-osdu"
    )

    # TODO: review and setup log/traces accordingly upon needs
    raise NotImplementedError("anthos initialization not implemented")
