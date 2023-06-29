# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http:#www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from osdu_aws.storage.storage_aws import AwsStorage
from osdu.core.api.storage.tenant import Tenant
from . import constants
from os import environ


def initialize_provider(app):
    aws_region = environ.get(constants.AWS_REGION, "us-east-1")
    aws_instance = environ.get(constants.OSDU_INSTANCE_NAME, "main")

    app.state.blob_storage = AwsStorage(session=None, service_account_file=f"{aws_region}$${aws_instance}")
    app.state.get_tenant = lambda dp: Tenant(data_partition_id=dp, project_id="", bucket_name=f"{dp}-logstore-osdu")
