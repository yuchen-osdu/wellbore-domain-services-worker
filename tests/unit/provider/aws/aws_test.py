import pytest
from unittest.mock import MagicMock, patch
from wdmsworker.provider.aws import initialize_provider
from wdmsworker.provider.aws import constants
from os import environ
from osdu_aws.storage.storage_aws import AwsStorage


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
