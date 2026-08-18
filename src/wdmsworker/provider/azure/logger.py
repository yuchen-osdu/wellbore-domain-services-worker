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

import logging
import sys
from os import environ

from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs._internal.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME

from . import constants
from wdmsworker.constants import SERVICE_INTERNAL_NAME
from wdmsworker.http_middlewares import get_context


def init_logger(*, service_name) -> logging.LoggerAdapter:
    az_ai_instrumentation_str = environ.get(constants.AZ_AI_CONNECTION_STR_ENV_VAR)
    az_logger_level = environ.get(constants.AZ_LOGGER_LEVEL_ENV_VAR, "INFO")

    return create_azure_logger(
        service_name=service_name,
        az_ai_instrumentation_str=az_ai_instrumentation_str,
        az_logger_level=az_logger_level,
    )


class AzureContextLoggerAdapter(logging.LoggerAdapter):
    """
    This adapter adds contextual information into messages to be logged in Azure monitoring.
    It aims to add as custom properties contextual fields, following these instructions:
    https://docs.microsoft.com/en-us/azure/azure-monitor/app/opencensus-python
    """

    @staticmethod
    def _set_extra_attrs(properties):
        """
        Retrieve context created in basic middleware from request info to append them
        in log message as custom attributes
        """
        ctx = get_context()

        if ctx.correlation_id:
            properties.setdefault("correlation-id", ctx.correlation_id)

        if ctx.request_id:
            properties.setdefault("request-id", ctx.request_id)

        if ctx.partition_id:
            properties.setdefault("data-partition-id", ctx.partition_id)

        if ctx.app_key:
            properties.setdefault("app-key", ctx.app_key)

        if ctx.api_key:
            properties.setdefault("api-key", ctx.api_key)

    def process(self, msg, kwargs):
        """Add custom properties to logger message to be sent to AzureAppInsights"""
        custom_properties = dict()
        self._set_extra_attrs(custom_properties)
        kwargs["extra"] = dict(custom_dimensions=custom_properties)

        return msg, kwargs


def create_azure_logger(*, service_name, az_ai_instrumentation_str, az_logger_level):
    """
    Create logger with two handlers:
     - AzureLogHandler: to see Dependencies, Requests, Traces and Exception into Azure monitoring
     - [default] StreamHandler (c.f. logging.basicConfig() ) to see all logs into the std.out captured in container logs

     returns logger configured wrapped into ContextLoggerAdapter
    """

    from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter

    resource = Resource(attributes={SERVICE_NAME: service_name})

    logger_provider = LoggerProvider(resource=resource)
    set_logger_provider(logger_provider)
    if az_ai_instrumentation_str:
        exporter = AzureMonitorLogExporter(connection_string=az_ai_instrumentation_str)
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

    az_handler = LoggingHandler()
    if az_logger_level:
        az_handler.setLevel(logging.getLevelName(az_logger_level))

    # stdout handler for direct logging output to stdout.
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    # Acquire the logger for azure library
    _set_logger_handlers(
        logger_name="azure",
        log_level=logging.WARNING,
        handlers=[stdout_handler, az_handler],
    )

    # Acquire the logger for osdu-core-lib-python-azure
    _set_logger_handlers(
        logger_name="osdu_az",
        log_level=logging.WARNING,
        handlers=[stdout_handler, az_handler],
    )

    # Acquire the logger for wdms-worker
    logger = _set_logger_handlers(
        logger_name=SERVICE_INTERNAL_NAME,
        log_level=logging.INFO,
        handlers=[stdout_handler, az_handler],
    )

    return AzureContextLoggerAdapter(logger, extra=dict())


def _set_logger_handlers(logger_name, log_level, handlers: list):
    """Retrieve logger by its name and add handlers to it"""
    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)

    for handler in handlers:
        if handler:
            logger.addHandler(handler)

    return logger
