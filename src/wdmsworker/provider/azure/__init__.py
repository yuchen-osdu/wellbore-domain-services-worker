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

from .logger import init_logger
from . import constants as azure_constants

from osdu_az.storage.blob_storage_az import AzureAioBlobStorage
from opencensus.ext.azure.trace_exporter import AzureExporter
from osdu.core.api.storage.tenant import Tenant

from ...constants import SERVICE_NAME, SERVICE_NAME_ENV_VAR


def rename_cloud_role_func(service_name):
    """
    Return a processor function to change 'Cloud Role Name' in AppInsight with given service_name variable.
    It's used by AzureLogHandler and AzureExporter.
    https://docs.microsoft.com/en-us/azure/azure-monitor/app/api-filtering-sampling#opencensus-python-telemetry-processors
    """

    def callback_func(envelope):
        envelope.tags["ai.cloud.role"] = service_name
        return True

    return callback_func


def initialize_provider(app):
    # "Service name" is set in yaml manifest file
    service_name = environ.get(SERVICE_NAME_ENV_VAR, SERVICE_NAME)
    app.state.logger = init_logger(service_name=service_name)

    app.state.blob_storage = AzureAioBlobStorage()
    app.state.get_tenant = lambda dp: Tenant(data_partition_id=dp, project_id="", bucket_name="wdms-osdu")

    az_ai_instrumentation_key = environ.get(azure_constants.AZ_AI_INSTRUMENTATION_KEY_ENV_VAR)
    if az_ai_instrumentation_key:
        traces_exporter = AzureExporter(connection_string=f"InstrumentationKey={az_ai_instrumentation_key}")
        traces_exporter.add_telemetry_processor(rename_cloud_role_func(service_name))
        app.state.traces_exporter = traces_exporter
