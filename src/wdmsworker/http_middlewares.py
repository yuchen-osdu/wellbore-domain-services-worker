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

from fastapi import Request
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from opencensus.trace import tracer as open_tracer
from opencensus.trace.samplers import AlwaysOnSampler
from opencensus.trace.span import SpanKind
from opencensus.trace.propagation.trace_context_http_header_format import TraceContextPropagator
from opencensus.trace.attributes_helper import COMMON_ATTRIBUTES

from . import constants


# Class used to propagate traces through requests' header
_trace_propagator = TraceContextPropagator()
_paths_suffix_to_skip = tuple(["healthz", "readiness", "liveness"])


async def logging_exception_middleware(request: Request, call_next):
    from .logger import get_logger_from_request

    log = get_logger_from_request(request)
    try:
        return await call_next(request)
    except Exception:
        log.exception(f"Exception occurred when calling: '{request.url.path}'")
        raise


def _add_request_attributes_to_span(request, response, span):
    """Add request's attributes into the given opencensus span"""
    span.add_attribute(
        attribute_key=constants.CORRELATION_ID_HEADER_NAME,
        attribute_value=request.headers.get(constants.CORRELATION_ID_HEADER_NAME),
    )
    span.add_attribute(attribute_key=COMMON_ATTRIBUTES["HTTP_METHOD"], attribute_value=request.method)
    span.add_attribute(attribute_key=COMMON_ATTRIBUTES["HTTP_ROUTE"], attribute_value=request.url.path)
    span.add_attribute(attribute_key=COMMON_ATTRIBUTES["HTTP_URL"], attribute_value=str(request.url))

    response_status = response.status_code if response else HTTP_500_INTERNAL_SERVER_ERROR
    span.add_attribute(attribute_key=COMMON_ATTRIBUTES["HTTP_STATUS_CODE"], attribute_value=response_status)

    # # this field is filled only after request is performed
    if request.scope.get("route"):
        span.add_attribute(
            attribute_key=COMMON_ATTRIBUTES["HTTP_ROUTE"], attribute_value=request.scope.get("route").path
        )


def _retrieve_traces_exporter(request: Request):
    """Return traces exporter store in App from Request if exists else None"""
    if request and request.app:
        try:
            return request.app.state.traces_exporter
        except AttributeError:
            pass
    return None


async def tracing_middleware(request: Request, call_next):
    """
    Before each incoming request, create a new trace and add it some request's attributes.
    Retrieve existing tracing context from headers if exists (following https://www.w3.org/TR/trace-context/)
    Probes routes are not traced, c.f. '_paths_suffix_to_skip' variable.

    Note: An exporter is required to visualize those traces on CSP front-end, c.f. 'on_startup_event()'
    """
    if request.url.path.endswith(_paths_suffix_to_skip):
        return await call_next(request)

    # Create tracing context, from headers if exists, else create a new one
    span_context = _trace_propagator.from_headers(request.headers)

    tracer = open_tracer.Tracer(
        span_context=span_context,
        sampler=AlwaysOnSampler(),
        propagator=_trace_propagator,
        exporter=_retrieve_traces_exporter(request),
    )

    with tracer.span(request.url.path) as parent_span:
        parent_span.span_kind = SpanKind.SERVER
        response = await call_next(request)
        _add_request_attributes_to_span(request, response, tracer.current_span())
        return response
