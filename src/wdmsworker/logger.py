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

from typing import Dict
import logging
from .constants import SERVICE_INTERNAL_NAME
from fastapi import Request
from . import constants

wdms_logger = logging.getLogger(SERVICE_INTERNAL_NAME)


def get_logger():
    return wdms_logger


class RequestContextAdapter(logging.LoggerAdapter):
    """Enrich logger with request context by appending attributes after message logged"""

    def process(self, msg, kwargs):
        my_context = self.extra["request_context"]
        return "%s | %s" % (msg, my_context), kwargs


def get_logger_from_request(request: Request):
    """ " Return logger enriched with request attributes: correlation-id, request-id"""

    request_context: Dict[str, str] = {}
    if request.headers.get(constants.CORRELATION_ID_HEADER_NAME):
        request_context.setdefault("correlation-id", request.headers[constants.CORRELATION_ID_HEADER_NAME])

    if request.headers.get(constants.REQUEST_ID_HEADER_NAME):
        request_context.setdefault("request-id", request.headers[constants.REQUEST_ID_HEADER_NAME])

    if request.headers.get(constants.PARTITION_ID_HEADER_NAME):
        request_context.setdefault("data-partition-id", request.headers[constants.PARTITION_ID_HEADER_NAME])

    extra = {"request_context": request_context}
    return RequestContextAdapter(wdms_logger, extra=extra)


def set_logger(logger):
    global wdms_logger
    wdms_logger = logger


def attach_logging_middleware_to_app(fastapi_app):
    """
    Adds a http middleware to given fastApi app object to log unexpected Python exceptions occurring when processing
    incoming requests. Log entries can be enriched with headers if provided: "correlation-id", "request-id" and
    "data-partition-id".
    """

    @fastapi_app.middleware("http")
    async def logging_exception_middleware(request: Request, call_next):
        log = get_logger_from_request(request)
        try:
            return await call_next(request)
        except Exception:
            log.exception(f"Exception occurred when calling: '{request.url.path}'")
            raise
