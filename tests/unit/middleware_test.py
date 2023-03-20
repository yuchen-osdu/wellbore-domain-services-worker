import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from unittest import mock

from wdmsworker.logger import attach_logging_middleware_to_app


def test_logging_middleware():
    with mock.patch("wdmsworker.logger.get_logger_from_request", mock.Mock(return_value=mock.Mock())) as mock_logger:
        app = FastAPI()
        client = TestClient(app)

        attach_logging_middleware_to_app(app)

        @app.get("/raising-route")
        def route():
            raise RuntimeError("Exception simulated!")

        with pytest.raises(RuntimeError):
            client.get("/raising-route")

        mock_logger().exception.assert_called_with("Exception occurred when calling: '/raising-route'")
