import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from unittest import mock

from opencensus.trace import tracer as open_tracer
from opencensus.trace.attributes_helper import COMMON_ATTRIBUTES
from opencensus.trace.propagation.trace_context_http_header_format import TraceContextPropagator
from opencensus.trace.samplers import AlwaysOnSampler
from starlette.middleware.base import BaseHTTPMiddleware

from wdmsworker import constants
from wdmsworker.dependencies import (
    accept_dependency,
    json_orient_dependency,
    blob_storage_dependency,
    tenant_dependency,
)
from wdmsworker.http_middlewares import (
    tracing_middleware,
    logging_exception_middleware,
)


def test_logging_middleware():
    with mock.patch("wdmsworker.logger.get_logger_from_request", mock.Mock(return_value=mock.Mock())) as mock_logger:
        app = FastAPI()
        app.add_middleware(BaseHTTPMiddleware, dispatch=logging_exception_middleware)

        client = TestClient(app)

        @app.get("/raising-route")
        def route():
            raise RuntimeError("Exception simulated!")

        with pytest.raises(RuntimeError):
            client.get("/raising-route")

        mock_logger().exception.assert_called_with("Exception occurred when calling: '/raising-route'")


@pytest.fixture()
def _setup_app_with_tracing_middleware():
    from wdmsworker.bulk import read_router

    mock_exporter = mock.Mock()

    app = FastAPI()
    app.state.traces_exporter = mock_exporter
    app.add_middleware(BaseHTTPMiddleware, dispatch=tracing_middleware)

    app.dependency_overrides[accept_dependency] = lambda: None
    app.dependency_overrides[json_orient_dependency] = lambda: None
    app.dependency_overrides[blob_storage_dependency] = lambda: None
    app.dependency_overrides[tenant_dependency] = lambda: None

    app.add_api_route("/data/{record_id}/{bulk_id}", read_router.get_bulk_route)

    @app.get("/tracing-route")
    def route():
        pass

    client = TestClient(app)
    yield client, mock_exporter


def _extract_span_data_from_mock(_mock_exporter, call_index):
    calls = _mock_exporter.mock_calls[call_index]
    args_called_tuple = calls[1]
    return args_called_tuple[0][0]


def test_ensure_parent_tracing_is_used(_setup_app_with_tracing_middleware):
    client, mock_exporter = _setup_app_with_tracing_middleware

    client.get("/tracing-route")

    span_data = _extract_span_data_from_mock(mock_exporter, 0)
    assert span_data.parent_span_id is None

    fake_wdms_parent_tracer = open_tracer.Tracer(sampler=AlwaysOnSampler(), propagator=TraceContextPropagator())
    with fake_wdms_parent_tracer.span("wdms-url") as parent_span:
        parent_tracing_headers = TraceContextPropagator().to_headers(fake_wdms_parent_tracer.span_context)
        client.get("/tracing-route", headers={**parent_tracing_headers})

    assert len(mock_exporter.mock_calls) == 2

    span_data = _extract_span_data_from_mock(mock_exporter, 1)
    assert span_data.context.from_header
    assert span_data.parent_span_id in parent_tracing_headers["traceparent"]
    assert span_data.context.span_id in parent_tracing_headers["traceparent"]
    assert span_data.context.trace_id in parent_tracing_headers["traceparent"]


@pytest.mark.parametrize(
    "called_url,traced_url,expected_status_code",
    [
        ("/tracing-route", "/tracing-route", 200),
        ("/data/record-id-123456/bulk-id-654321", "/data/{record_id}/{bulk_id}", 500),
    ],
)
def test_tracing_middleware(_setup_app_with_tracing_middleware, called_url, traced_url, expected_status_code):
    client, mock_exporter = _setup_app_with_tracing_middleware
    client.get(called_url, headers={constants.CORRELATION_ID_HEADER_NAME: "my-correlation-id"})

    calls = mock_exporter.mock_calls[0]
    method_called = calls[0]

    span_data = _extract_span_data_from_mock(mock_exporter, 0)
    assert method_called == "export"
    assert span_data.name == called_url

    assert span_data.attributes.get(constants.CORRELATION_ID_HEADER_NAME) == "my-correlation-id"
    assert span_data.attributes.get(COMMON_ATTRIBUTES["HTTP_METHOD"]) == "GET"
    assert span_data.attributes.get(COMMON_ATTRIBUTES["HTTP_ROUTE"]) == traced_url
    assert span_data.attributes.get(COMMON_ATTRIBUTES["HTTP_URL"]) == f"http://testserver{called_url}"
    assert span_data.attributes.get(COMMON_ATTRIBUTES["HTTP_STATUS_CODE"]) == expected_status_code
