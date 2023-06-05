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

from opencensus.log import TraceLogger
from opencensus.trace import config_integration
from opencensus.ext.azure.log_exporter import AzureLogHandler

from . import constants
from ...constants import SERVICE_INTERNAL_NAME


def init_logger(*, service_name) -> logging.LoggerAdapter:
    az_ai_instrumentation_key = environ.get(constants.AZ_AI_INSTRUMENTATION_KEY_ENV_VAR)
    az_logger_level = environ.get(constants.AZ_LOGGER_LEVEL_ENV_VAR, "INFO")

    return create_azure_logger(
        service_name=service_name,
        az_ai_instrumentation_key=az_ai_instrumentation_key,
        az_logger_level=az_logger_level,
    )


class AzureContextLoggerAdapter(logging.LoggerAdapter):
    """
    This adapter adds contextual information into messages to be logged in Azure monitoring.
    It aims to add as custom properties contextual fields, following this instructions:
    https://docs.microsoft.com/en-us/azure/azure-monitor/app/opencensus-python
    """

    @staticmethod
    def _set_extra_attrs(properties):
        """
        Retrieve context created in basic middleware from request info to append them
        in log message as custom attributes
        """
        pass
        # TODO restore that

    #     properties.setdefault('correlation-id', ctx.correlation_id)
    #     properties.setdefault('request-id', ctx.request_id)
    #     properties.setdefault('data-partition-id', ctx.partition_id)
    #     properties.setdefault('app-key', ctx.app_key)
    #     properties.setdefault('api-key', ctx.api_key)

    def process(self, msg, kwargs):
        """Add custom properties to logger message to be sent to AzureAppInsights"""
        custom_properties = dict()
        self._set_extra_attrs(custom_properties)
        kwargs["extra"] = dict(custom_dimensions=custom_properties)

        return msg, kwargs


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


def create_azure_logger(*, service_name, az_ai_instrumentation_key, az_logger_level):
    """
    Create logger with two handlers:
     - AzureLogHandler: to see Dependencies, Requests, Traces and Exception into Azure monitoring
     - [default] StreamHandler (c.f. logging.basicConfig() ) to see all logs into the std.out captured in container logs

     returns logger configured wrapped into ContextLoggerAdapter
    """

    # Ensure exceptions will be attached to opencensus requests in AppInsights by modifying wdms logger meta class
    config_integration.trace_integrations(["logging"])

    # stdout handler for direct logging output to stdout.
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    #  AzurelogHandler for logging to azure AppInsights
    key = az_ai_instrumentation_key
    logger_level = az_logger_level
    if key:
        az_handler = AzureLogHandler(connection_string=f"InstrumentationKey={key}")
        az_handler.setLevel(logging.getLevelName(logger_level))
        az_handler.add_telemetry_processor(rename_cloud_role_func(service_name))
    else:
        az_handler = None

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

    if az_handler:
        assert isinstance(logger, TraceLogger), (
            f"Logger '{SERVICE_INTERNAL_NAME}' has been created before this line, link between requests and exceptions "
            "won't work properly"
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
