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

import logging

from osdu_aws.storage.storage_aws import AwsStorage
from osdu.core.api.storage.tenant import Tenant
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from . import constants
from os import environ

logger = logging.getLogger(__name__)


def initialize_provider(app):
    aws_region = environ.get(constants.AWS_REGION, "us-east-1")
    aws_instance = environ.get(constants.OSDU_INSTANCE_NAME, "main")

    app.state.blob_storage = AwsStorage(session=None, service_account_file=f"{aws_region}$${aws_instance}")
    app.state.get_tenant = lambda dp: Tenant(data_partition_id=dp, project_id="", bucket_name=f"{dp}-logstore-osdu")

    # Resource attributes (service name, X-Ray/AppSignals hosting keys) come from the
    # OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES env vars the chart sets; Resource.create()
    # reads them via the OTEL env detector. Passing explicit attributes here would suppress
    # those and break X-Ray/AppSignals hosting.
    resource = Resource.create()
    provider = TracerProvider(resource=resource)

    # For the proto-http exporter this must be the full signal URL ending in /v1/traces
    # (e.g. http://collector:4318/v1/traces). Unlike the base OTEL_EXPORTER_OTLP_ENDPOINT, the
    # traces-specific variable is used verbatim and is not auto-suffixed with the signal path.
    endpoint = environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if endpoint:
        # A malformed OTEL_EXPORTER_OTLP_* config (bad headers, unreadable cert path) can raise
        # here; keep it non-fatal so a tracing misconfig never sends the worker into CrashLoopBackOff.
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        except Exception:
            logger.exception("Failed to initialize OTLP span exporter, worker traces will not be exported")
    else:
        logger.warning("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT not set, worker traces will not be exported")

    # Sets the global default tracer provider used by the server-span middleware.
    trace.set_tracer_provider(provider)
    return provider
