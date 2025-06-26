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

import os
from unittest import mock
import pytest
from asgi_lifespan import LifespanManager
from httpx import AsyncClient, ASGITransport
from wdmsworker.app import app
from wdmsworker import constants


@pytest.fixture(autouse=True)
def mock_settings_env_vars(tmp_path):
    # force local
    with mock.patch.dict(
        os.environ, {constants.CLOUD_PROVIDER_ENV_VAR: "local", "USE_LOCALFS_BLOB_STORAGE_WITH_PATH": str(tmp_path)}
    ):
        yield


@pytest.fixture(autouse=True)
async def app_initialized_with_testclient(mock_settings_env_vars):
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test_wdms_worker") as client:
            yield app, client


@pytest.mark.anyio
async def test_app_can_be_mounted(app_initialized_with_testclient):
    _, client = app_initialized_with_testclient
    response = await client.get(constants.API_PREFIX + "/healthz")
    assert response.status_code == 200
