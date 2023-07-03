import logging
import re
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
from wdmsworker.constants import SERVICE_INTERNAL_NAME
from wdmsworker.dependencies import (
    accept_dependency,
    json_orient_dependency,
    blob_storage_dependency,
    tenant_dependency,
)
from wdmsworker.http_middlewares import (
    tracing_middleware,
    logging_exception_middleware,
    context_middleware,
    get_context,
    add_middlewares_to_app,
)
from wdmsworker.logger import get_logger, RequestContextAdapter


class CodeHasBeenReachedException(Exception):
    """To ensure the code inside middleware is really reached, raise this exception at end and catch it later"""

    pass


def test_logging_middleware():
    with mock.patch("wdmsworker.logger.get_logger_from_request", mock.Mock(return_value=mock.Mock())) as mock_logger:
        app = FastAPI()
        app.add_middleware(BaseHTTPMiddleware, dispatch=logging_exception_middleware)

        client = TestClient(app)

        @app.get("/raising-route")
        def route():
            raise CodeHasBeenReachedException("Exception simulated!")

        with pytest.raises(CodeHasBeenReachedException):
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
    client.get(
        called_url,
        headers={
            constants.CORRELATION_ID_HEADER_NAME: "my-correlation-id",
            constants.PARTITION_ID_HEADER_NAME: "my-partition-id",
            constants.REQUEST_ID_HEADER_NAME: "my-request-id",
        },
    )

    calls = mock_exporter.mock_calls[0]
    method_called = calls[0]

    span_data = _extract_span_data_from_mock(mock_exporter, 0)
    assert method_called == "export"
    assert span_data.name == called_url

    assert span_data.attributes.get(constants.CORRELATION_ID_HEADER_NAME) == "my-correlation-id"
    assert span_data.attributes.get(constants.PARTITION_ID_HEADER_NAME) == "my-partition-id"
    assert span_data.attributes.get(constants.REQUEST_ID_HEADER_NAME) == "my-request-id"

    assert span_data.attributes.get(COMMON_ATTRIBUTES["HTTP_METHOD"]) == "GET"
    assert span_data.attributes.get(COMMON_ATTRIBUTES["HTTP_ROUTE"]) == traced_url
    assert span_data.attributes.get(COMMON_ATTRIBUTES["HTTP_URL"]) == f"http://testserver{called_url}"
    assert span_data.attributes.get(COMMON_ATTRIBUTES["HTTP_STATUS_CODE"]) == expected_status_code


def test_ctx_middleware_accessible_from_endpoints():
    """Ensure the context middleware is called and correctly initialized"""

    app = FastAPI()
    app.add_middleware(BaseHTTPMiddleware, dispatch=context_middleware)
    client = TestClient(app)

    @app.get("/ctx-route-test")
    def route():
        request_ctx = get_context()
        assert request_ctx is not None

        assert request_ctx.logger is None
        assert request_ctx.tracer is None

        raise CodeHasBeenReachedException("Endpoint called")

    with pytest.raises(CodeHasBeenReachedException, match="Endpoint called"):
        client.get("/ctx-route-test")


def test_ctx_middleware_with_logger():
    """Ensure middlewares: context + logging work properly together. So, logger is available inside context object"""

    app = FastAPI()
    app.add_middleware(BaseHTTPMiddleware, dispatch=logging_exception_middleware)
    app.add_middleware(BaseHTTPMiddleware, dispatch=context_middleware)

    client = TestClient(app)

    @app.get("/ctx-route-test")
    def route():
        request_ctx = get_context()
        assert request_ctx.logger

        request_ctx.logger.info("Test message")
        raise CodeHasBeenReachedException("Endpoint called")

    with pytest.raises(CodeHasBeenReachedException, match="Endpoint called"):
        client.get("/ctx-route-test")


@pytest.mark.parametrize(
    "middlewares_order,expected_exception,expected_exception_message",
    [
        ([tracing_middleware, context_middleware], CodeHasBeenReachedException, "Endpoint called"),
        ([logging_exception_middleware, context_middleware], CodeHasBeenReachedException, "Endpoint called"),
        (
            [tracing_middleware, logging_exception_middleware, context_middleware],
            CodeHasBeenReachedException,
            "Endpoint called",
        ),
        (
            [logging_exception_middleware, tracing_middleware, context_middleware],
            CodeHasBeenReachedException,
            "Endpoint called",
        ),
        (
            [context_middleware, tracing_middleware],
            AssertionError,
            # tracer is not available even tracing + context middleware create but not in the correct order
            re.escape("tracer object should not be None\nassert None\n +  where None = ServiceContext().tracer"),
        ),
        ([tracing_middleware], AssertionError, "context object is None"),
    ],
)
def test_ctx_middleware_with_tracer(middlewares_order, expected_exception, expected_exception_message):
    app = FastAPI()
    app.state.traces_exporter = mock.Mock()

    for middleware in middlewares_order:
        app.add_middleware(BaseHTTPMiddleware, dispatch=middleware)

    client = TestClient(app)

    @app.get("/ctx-route-test")
    def route():
        request_ctx = get_context()
        assert request_ctx, "context object is None"

        if tracing_middleware in middlewares_order:
            assert request_ctx.tracer, "tracer object should not be None"
        else:
            assert request_ctx.tracer is None

        if logging_exception_middleware in middlewares_order:
            assert request_ctx.logger, "logger object should not be None"
        else:
            assert request_ctx.logger is None

        raise CodeHasBeenReachedException("Endpoint called")

    with pytest.raises(expected_exception, match=expected_exception_message):
        client.get("/ctx-route-test")


def test_middlewares_order():
    with mock.patch("wdmsworker.http_middlewares.logging_exception_middleware") as logging_mock:
        with mock.patch("wdmsworker.http_middlewares.tracing_middleware") as tracing_mock:
            with mock.patch("wdmsworker.http_middlewares.context_middleware") as context_mock:
                super_app = FastAPI()

                add_middlewares_to_app(super_app)

                assert len(super_app.user_middleware) == 3
                middlewares_name = [m.options["dispatch"]._mock_name for m in super_app.user_middleware]
                assert middlewares_name[0] == "context_middleware", "Context middleware needs to be the first one "


def test_get_logger_fct():
    app = FastAPI()
    app.add_middleware(BaseHTTPMiddleware, dispatch=logging_exception_middleware)
    app.add_middleware(BaseHTTPMiddleware, dispatch=context_middleware)

    client = TestClient(app)

    @app.get("/ctx-route-test")
    def route():
        assert logging.getLogger(SERVICE_INTERNAL_NAME) != get_context().logger

        assert isinstance(get_logger(), RequestContextAdapter)
        assert get_logger() == get_context().logger, "withing a endpoint logger should be the enriched logger"

        assert (
            get_logger().extra["request_context"] == sent_headers
        ), "enriched logger should store request's headers to log them"

        raise CodeHasBeenReachedException("Endpoint called")

    assert isinstance(get_logger(), logging.Logger)
    assert get_logger() == logging.getLogger(SERVICE_INTERNAL_NAME), "out of endpoint, logger should be the default one"

    sent_headers = {
        constants.CORRELATION_ID_HEADER_NAME: "my-correlation-id",
        constants.PARTITION_ID_HEADER_NAME: "my-partition-id",
        constants.REQUEST_ID_HEADER_NAME: "my-request-id",
    }

    with pytest.raises(CodeHasBeenReachedException, match="Endpoint called"):
        client.get("/ctx-route-test", headers=sent_headers)
