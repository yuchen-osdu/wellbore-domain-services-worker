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
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

from .logger import init_logger
from . import constants as azure_constants

from osdu_az.storage.blob_storage_az import AzureAioBlobStorage
from opentelemetry.sdk.resources import Resource, SERVICE_NAME as SERVICE_NAME_ATTRIBUTE
from osdu.core.api.storage.tenant import Tenant

from wdmsworker.constants import SERVICE_NAME, SERVICE_NAME_ENV_VAR


def initialize_provider(app):
    # "Service name" is set in yaml manifest file
    service_name = environ.get(SERVICE_NAME_ENV_VAR, SERVICE_NAME)
    app.state.logger = init_logger(service_name=service_name)

    app.state.blob_storage = AzureAioBlobStorage()
    app.state.get_tenant = lambda dp: Tenant(data_partition_id=dp, project_id="", bucket_name="wdms-osdu")

    resource = Resource(attributes={SERVICE_NAME_ATTRIBUTE: service_name})

    provider = TracerProvider(resource=resource)

    az_ai_instrumentation_str = environ.get(azure_constants.AZ_AI_CONNECTION_STR_ENV_VAR)
    if az_ai_instrumentation_str:
        exporter = AzureMonitorTraceExporter(connection_string=az_ai_instrumentation_str)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    # Sets the global default tracer provider
    trace.set_tracer_provider(provider)
    return provider
