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

from os import environ
from logging import getLogger

from fastapi import FastAPI, Request


from . import get_version
from . import constants
from .provider import initialize_for_provider
from .bulk.write_router import write_bulk_router
from .bulk.read_router import read_bulk_router
from .statistics.statistics_routes import (
    router as statistics_router,
    BulkStatisticsHTTPException,
    http_stats_error_handler,
)
from .http_middlewares import (
    add_middlewares_to_app,
)

open_api_prefix = environ.get(constants.OPENAPI_PREFIX_ENV_VAR, constants.API_PREFIX)

app = FastAPI(
    title="Wellbore domain services worker",
    version=get_version(),
    root_path=open_api_prefix,
)

base = FastAPI()
base.mount(open_api_prefix, app)

add_middlewares_to_app(app)


@base.on_event("startup")
async def base_startup_event():
    # needed as FastAPI don't called mounted app startup_event by itself + TestClient compatibility
    await on_startup_event()


@app.on_event("startup")
async def on_startup_event():
    """
    Code hook for cloud provider specific code for:
        - storage access
        - logging export (optional)
    """

    provider = environ.get(constants.CLOUD_PROVIDER_ENV_VAR, "local")
    initialize_for_provider(provider, app)

    logger = getLogger(constants.SERVICE_INTERNAL_NAME)
    app.state.logger = logger
    logger.info(f"startup DONE for provider {provider}")


@base.on_event("shutdown")
async def base_on_shutdown_event():
    await on_shutdown_event()


@app.on_event("shutdown")
async def on_shutdown_event():
    app.state.logger.info("shutdown DONE")


# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ---------------------- PROBES ---------------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------


@app.get("/healthz", include_in_schema=False)
async def health_route():
    pass


@app.get("/readiness", include_in_schema=False)
async def readiness_route():
    pass


@app.get("/liveness", include_in_schema=False)
async def liveness_route():
    pass


# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ----------------------- ABOUT ---------------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------


@app.get("/about")
async def about_route(request: Request):
    from .logger import get_logger_from_request

    loggy = get_logger_from_request(request)
    loggy.info("An example of logging with request context")

    return {"version": get_version()}


# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ----------------------- R/W Bulk ROUTE ------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------


@app.exception_handler(BulkStatisticsHTTPException)
async def _http_stats_error_handler_wrapper(
    request,
    e: BulkStatisticsHTTPException,
):
    return await http_stats_error_handler(request, e)


app.include_router(write_bulk_router)
app.include_router(read_bulk_router)
app.include_router(statistics_router)
