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

# environment variables names
CLOUD_PROVIDER_ENV_VAR = "CLOUD_PROVIDER"
AZ_LOGGER_LEVEL_ENV_VAR = "AZ_LOGGER_LEVEL"
OPENAPI_PREFIX_ENV_VAR = "OPENAPI_PREFIX"

#

CLOUD_PROVIDER_AZURE = "az"
CLOUD_PROVIDER_AWS = "aws"
CLOUD_PROVIDER_LOCAL = "local"
SERVICE_INTERNAL_NAME = "wdmsworker"
API_PREFIX = "/api/wdms-worker"

CORRELATION_ID_HEADER_NAME = "correlation-id"
REQUEST_ID_HEADER_NAME = "request-id"
PARTITION_ID_HEADER_NAME = "data-partition-id"
