"""
This test ensures the API spec committed with the sources stays accurate.
If the test fails, it replaces the saved spec with the current version.
The updated spec file must then be committed with the latest changes.
"""

import json
import os
from pathlib import Path
from unittest import mock

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from wdmsworker import constants
from wdmsworker.app import app

# docs/api/community/v1 is the shared CI job's default location, not an entity API version.
OPENAPI_PATH = Path(__file__).resolve().parents[3] / "docs" / "api" / "community" / "v1" / "openapi.json"


def _baseline_document(worker_app) -> dict:
    # Copy the schema. FastAPI adds root_path to servers on the first HTTP request,
    # not necessarily on app.openapi(), and the cached schema must stay unchanged.
    return {**worker_app.openapi(), "servers": [{"url": constants.API_PREFIX}]}


def _dumps(document: dict) -> str:
    return json.dumps(document, sort_keys=True, indent=2)


@pytest.fixture
def mock_settings_env_vars(tmp_path):
    with mock.patch.dict(
        os.environ,
        {constants.CLOUD_PROVIDER_ENV_VAR: "local", "USE_LOCALFS_BLOB_STORAGE_WITH_PATH": str(tmp_path)},
    ):
        yield


@pytest.fixture
async def app_initialized_with_testclient(mock_settings_env_vars):
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test_wdms_worker") as client:
            yield app, client


@pytest.fixture
async def openapi_json(app_initialized_with_testclient):
    worker_app, _ = app_initialized_with_testclient
    yield _baseline_document(worker_app)


@pytest.mark.anyio
async def test_api_spec(openapi_json):
    openapi_text = _dumps(openapi_json)
    with open(OPENAPI_PATH, "r") as specfile:
        specfile_text = _dumps(json.load(specfile))
    if openapi_text != specfile_text:
        with open(OPENAPI_PATH, "w") as specfile:
            specfile.write(openapi_text)
            specfile.write("\n")
        assert False, f"{OPENAPI_PATH} has changed, commit the updated file"


@pytest.mark.anyio
async def test_served_api_spec_matches_baseline(openapi_json, app_initialized_with_testclient):
    _, client = app_initialized_with_testclient
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json() == openapi_json


@pytest.mark.anyio
async def test_api_spec_for_duplicates(openapi_json):
    path_dict = openapi_json.get("paths")
    operation_id_set = set()
    assert path_dict is not None
    for url, url_dict in path_dict.items():
        for method, method_dict in url_dict.items():
            operation_id = method_dict.get("operationId")
            assert operation_id not in operation_id_set, f"{method}:{url} {operation_id} already defined"
            operation_id_set.add(operation_id)
