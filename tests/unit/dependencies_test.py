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

from unittest.mock import Mock
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from wdmsworker import dependencies
from wdmsworker.model.mime_types import MimeTypes, MimeType


def test_data_partition_dependency():
    app = FastAPI()
    client = TestClient(app)

    @app.get("/")
    async def route(value=Depends(dependencies.data_partition_dependency)):
        return {"value": str(value)}

    response = client.get("/", headers={"data-partition-id": "MY_PARTITION"})
    assert response.json() == {"value": "MY_PARTITION"}

    response = client.get("/")
    assert response.status_code == 422


def test_correlation_id_dependency():
    app = FastAPI()
    client = TestClient(app)

    @app.get("/")
    def route(value=Depends(dependencies.correlation_id_dependency)):
        return {"value": str(value)}

    response = client.get("/", headers={"correlation-id": "MY_CID"})
    assert response.json() == {"value": "MY_CID"}

    response = client.get("/")
    assert response.status_code == 200
    assert len(response.json()["value"]) > 0


def make_assert_mime_eq(header, dependency):
    app = FastAPI()
    client = TestClient(app)

    @app.get("/")
    def route(value: MimeType = Depends(dependency)):
        return {"value": value.type if value is not None else "NONE"}

    def check_mime_type(input_mime, expected_mime):
        response = client.get("/", headers={header: input_mime} if input_mime else {})
        assert response.status_code == 200
        if expected_mime is None:
            assert response.json()["value"] == "NONE"
        else:
            assert MimeTypes.from_str(response.json()["value"])

    return check_mime_type


def test_content_type_dependency():
    assert_mime_eq = make_assert_mime_eq("Content-Type", dependencies.content_type_dependency)

    assert_mime_eq("application/json", MimeTypes.JSON)
    assert_mime_eq("application/parquet", MimeTypes.PARQUET)
    assert_mime_eq("application/x-parquet", MimeTypes.PARQUET)
    assert_mime_eq("text/plain", None)
    assert_mime_eq(None, None)


def test_accept_dependency():
    assert_mime_eq = make_assert_mime_eq("Accept", dependencies.accept_dependency)

    assert_mime_eq("application/json", MimeTypes.JSON)
    assert_mime_eq("application/parquet", MimeTypes.PARQUET)
    assert_mime_eq("application/x-parquet", MimeTypes.PARQUET)
    assert_mime_eq("text/plain", None)
    assert_mime_eq("*/*", MimeTypes.ANY)
    assert_mime_eq(None, MimeTypes.ANY)  # client autofill accept with '*/*'


def test_get_blob_storage_dependency():
    app = FastAPI()
    app.state.blob_storage = Mock(return_value="blob storage mock")
    client = TestClient(app)

    @app.get("/")
    def route(blob_storage=Depends(dependencies.blob_storage_dependency)):
        return {"value": blob_storage()}

    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["value"] == "blob storage mock"


def test_tenant_dependency():
    app = FastAPI()
    app.state.get_tenant = lambda dp: f"tenant for data partition {dp}"
    client = TestClient(app)

    @app.get("/")
    def route(tenant=Depends(dependencies.tenant_dependency)):
        return {"value": tenant}

    response = client.get("/", headers={"data-partition-id": "MY_PARTITION"})
    assert response.status_code == 200
    assert response.json()["value"] == "tenant for data partition MY_PARTITION"

    response = client.get("/")
    assert response.status_code == 422
