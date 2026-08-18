# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.​
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

import pytest
from unittest.mock import MagicMock, patch
from wdmsworker.provider.aws import initialize_provider
from wdmsworker.provider.aws import constants
from os import environ
from osdu_aws.storage.storage_aws import AwsStorage

OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"


# @pytest.mark.unit
def test_initialize_provider(test_tenant):
    mock_ssm_client = MagicMock()
    mock_sts_client = MagicMock()
    # Mock the environment variables
    with patch.dict("os.environ", {constants.AWS_REGION: "test-region", constants.OSDU_INSTANCE_NAME: "test-instance"}):
        # Mock AwsStorage
        with patch("osdu_aws.storage.storage_aws.AwsStorage") as MockAwsStorage:
            with patch("boto3.client") as mock_boto_client:

                def client_side_effect(service, *args, **kwargs):
                    return mock_ssm_client if service == "ssm" else mock_sts_client

                mock_boto_client.side_effect = client_side_effect

                mock_app = MagicMock()  # Create a mock app

                # Call the function to test
                initialize_provider(mock_app)

                # Testing the lambda
                tenant = mock_app.state.get_tenant("dp")
                assert tenant.data_partition_id == test_tenant.data_partition_id
                assert tenant.bucket_name.endswith("-logstore-osdu")


def test_initialize_provider_wires_otlp_exporter_when_endpoint_set(test_tenant):
    otlp_endpoint = "http://localhost:4318/v1/traces"
    env = {
        constants.AWS_REGION: "test-region",
        constants.OSDU_INSTANCE_NAME: "test-instance",
        OTLP_ENDPOINT_ENV: otlp_endpoint,
    }
    with patch.dict("os.environ", env):
        with patch("osdu_aws.storage.storage_aws.AwsStorage"):
            with patch("boto3.client"):
                with (
                    patch("wdmsworker.provider.aws.TracerProvider") as MockTracerProvider,
                    patch("wdmsworker.provider.aws.BatchSpanProcessor") as MockBatchSpanProcessor,
                    patch(
                        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"
                    ) as MockOTLPSpanExporter,
                ):
                    mock_provider = MockTracerProvider.return_value

                    returned = initialize_provider(MagicMock())

                    MockOTLPSpanExporter.assert_called_once_with(endpoint=otlp_endpoint)
                    MockBatchSpanProcessor.assert_called_once_with(MockOTLPSpanExporter.return_value)
                    mock_provider.add_span_processor.assert_called_once_with(MockBatchSpanProcessor.return_value)
                    assert returned is mock_provider


def test_initialize_provider_skips_export_when_endpoint_unset(test_tenant):
    env = {
        constants.AWS_REGION: "test-region",
        constants.OSDU_INSTANCE_NAME: "test-instance",
    }
    with patch.dict("os.environ", env, clear=False):
        environ.pop(OTLP_ENDPOINT_ENV, None)
        with patch("osdu_aws.storage.storage_aws.AwsStorage"):
            with patch("boto3.client"):
                with (
                    patch("wdmsworker.provider.aws.TracerProvider") as MockTracerProvider,
                    patch("wdmsworker.provider.aws.BatchSpanProcessor") as MockBatchSpanProcessor,
                ):
                    mock_provider = MockTracerProvider.return_value

                    returned = initialize_provider(MagicMock())

                    mock_provider.add_span_processor.assert_not_called()
                    MockBatchSpanProcessor.assert_not_called()
                    assert returned is mock_provider
