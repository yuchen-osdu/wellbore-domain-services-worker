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

import contextvars
from dataclasses import dataclass

from fastapi import Request
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR
from starlette.middleware.base import BaseHTTPMiddleware

from opentelemetry import trace
from opentelemetry.semconv.trace import SpanAttributes
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.trace import Status, StatusCode, SpanKind

from . import constants

# endpoints suffix to be ignored by traces
_paths_suffix_to_skip = tuple(["healthz", "readiness", "liveness"])


def add_middlewares_to_app(_app):
    """Add HTTP middleware to given FastAPI app in required order"""

    _app.add_middleware(BaseHTTPMiddleware, dispatch=logging_exception_middleware)
    _app.add_middleware(BaseHTTPMiddleware, dispatch=tracing_middleware)

    # this middleware needs to be added in last
    _app.add_middleware(BaseHTTPMiddleware, dispatch=context_middleware)


async def logging_exception_middleware(request: Request, call_next):
    """Create an enriched logger for each incoming request and log exceptions with stacktrace if happened"""

    from .logger import get_logger_from_request

    log = get_logger_from_request(request)
    ctx = get_context()
    if ctx:
        ctx.logger = log

    try:
        return await call_next(request)
    except Exception:
        log.exception(f"Exception occurred when calling: '{request.url.path}'")
        raise


def _add_request_attributes_to_span(request, response, span):
    """Add request's attributes into the given tracing span"""

    if correlation_id_header := request.headers.get(constants.CORRELATION_ID_HEADER_NAME):
        span.set_attribute(constants.CORRELATION_ID_HEADER_NAME, correlation_id_header)
    if partition_id_header := request.headers.get(constants.PARTITION_ID_HEADER_NAME):
        span.set_attribute(constants.PARTITION_ID_HEADER_NAME, partition_id_header)
    if request_id_header := request.headers.get(constants.REQUEST_ID_HEADER_NAME):
        span.set_attribute(constants.REQUEST_ID_HEADER_NAME, request_id_header)
    if user_id_header := request.headers.get(constants.X_USER_ID_HEADER_NAME):
        span.set_attribute(constants.X_USER_ID_HEADER_NAME, user_id_header)
    if app_id_header := request.headers.get(constants.APP_ID_HEADER_NAME):
        span.set_attribute(constants.APP_ID_HEADER_NAME, app_id_header)

    span.set_attribute(SpanAttributes.HTTP_METHOD, request.method)
    span.set_attribute(SpanAttributes.HTTP_ROUTE, request.url.path)
    span.set_attribute(SpanAttributes.HTTP_URL, str(request.url))

    response_status = response.status_code if response else HTTP_500_INTERNAL_SERVER_ERROR
    span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, response_status)

    if response_content_length := response.headers.get("Content-Length", None) if response else None:
        span.set_attribute("response.header Content-length", response_content_length)

    # this field is filled only after request is performed
    http_route = request.scope["route"].path if "route" in request.scope else request.scope["path"]
    span.set_attribute(SpanAttributes.HTTP_ROUTE, http_route)


def get_tracer():
    return trace.get_tracer(__name__)


async def tracing_middleware(request: Request, call_next):
    """
    Before each incoming request, create a new trace and add it some request's attributes.
    Retrieve existing tracing context from headers if exists (following https://www.w3.org/TR/trace-context/)
    Probes routes are not traced, c.f. '_paths_suffix_to_skip' variable.

    Note: An exporter is required to visualize those traces on CSP front-end, c.f. 'on_startup_event()'
    """
    if request.url.path.endswith(_paths_suffix_to_skip):
        return await call_next(request)

    tracer = get_tracer()
    tracing_ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)

    with tracer.start_as_current_span(name=request.url.path, kind=SpanKind.SERVER, context=tracing_ctx) as span:
        response = None
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            _add_request_attributes_to_span(request, response, span)


@dataclass
class ServiceContext:
    logger = None


# required to store context of incoming requests
__worker_ctx_var__: contextvars.ContextVar[ServiceContext] = contextvars.ContextVar("wdms_worker_internal_cxt_var")


def get_context():
    try:
        return __worker_ctx_var__.get()
    except LookupError:
        return None


async def context_middleware(request: Request, call_next):
    """
    Create a context for each incoming request.
    It uses contextvar library to store ServiceContext object that stores:
    - an enriched logger (correlation-id, data-partition-id and request-id),
    - a tracer required to create children traces.

    IMPORTANT: this middleware REQUIRES to be run in before all the other custom middlewares.
    """
    current_ctx = ServiceContext()

    token = __worker_ctx_var__.set(current_ctx)
    try:
        return await call_next(request)
    finally:
        __worker_ctx_var__.reset(token)
