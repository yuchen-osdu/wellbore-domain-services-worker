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

import tempfile
from uuid import uuid4
import pytest
from os import environ
import py
import subprocess
import requests
from requests.adapters import HTTPAdapter
from contextlib import suppress, contextmanager
import time


def pytest_addoption(parser):
    parser.addoption(
        "--no-subprocess",
        action="store_true",
        help=(
            "tested service is no longer started as a sub process but in the same than the test using FastAPI test"
            " client."
        ),
    )


@pytest.fixture(scope="session")
def no_sub_process_opt(request):
    return request.config.getoption("--no-subprocess")


@pytest.fixture(scope="session")
def session_dir(request):
    # TODO similar to pytest but 'py' will soon be removed https://github.com/pytest-dev/pytest/issues/7259
    #  + potentially prevent 3.11
    temp_dir = py.path.local(tempfile.mkdtemp())
    request.addfinalizer(lambda: temp_dir.remove(rec=1))
    # Any extra setup here
    return temp_dir


@pytest.fixture(scope="session")
def start_wdms_worker_service(session_dir, no_sub_process_opt):
    """
    Start service locally the same way than docker in order to be closer to production case and
    be as much decoupled from actual implementation as possible. The current drawback is that coverage is not
    properly computed.

    Could use FastAPI TestClient instead but it implies more coupling.

    :return: port of the service
    """

    if no_sub_process_opt:
        print("!!! using FastAPI TestClient !!!")
        environ["CLOUD_PROVIDER"] = "local"
        environ["USE_LOCALFS_BLOB_STORAGE_WITH_PATH"] = str(session_dir)
        yield ""
        return

    print("!!! starting worker service in sub process with uvicorn !!!")
    from socket import socket

    srv_env = environ.copy()
    srv_env["CLOUD_PROVIDER"] = "local"
    srv_env["USE_LOCALFS_BLOB_STORAGE_WITH_PATH"] = str(session_dir)

    # get random free port
    with socket() as s:
        s.bind(("", 0))
        port = s.getsockname()[1]
    r = subprocess.Popen(["uvicorn", "wdmsworker.app:base", "--host", "127.0.0.1", "--port", str(port)], env=srv_env)

    is_ready = False
    for _ in range(5):
        s = requests.Session()
        s.mount("http://", HTTPAdapter(max_retries=1))
        with suppress(Exception):
            is_ready = s.get(f"http://127.0.0.1:{port}/api/wdms-worker/readiness").status_code == 200
        if is_ready or r.poll() is not None:
            break
        time.sleep(1)

    if not is_ready:
        r.kill()
        pytest.exit("Failed to get service running and ready")

    print("Service is read on", f"http://127.0.0.1:{port}/api/wdms-worker")
    yield port

    r.kill()


# sub classing => https://github.com/psf/requests/issues/2554
class TestClientSession(requests.Session):
    def __init__(self, base_url=None, headers=None):
        super().__init__()
        self.prefix_url = base_url
        if headers is not None:
            self.headers.update(headers)

    def request(self, method, url, *args, **kwargs):
        full_url = f"{self.prefix_url}{url}"
        print(full_url)
        return super().request(method, full_url, *args, **kwargs)

    def get(self, url, **kwargs):
        kwargs.setdefault("allow_redirects", True)
        return self.request("GET", url, **kwargs)

    def options(self, url, **kwargs):
        kwargs.setdefault("allow_redirects", True)
        return self.request("OPTIONS", url, **kwargs)

    def head(self, url, **kwargs):
        kwargs.setdefault("allow_redirects", False)
        return self.request("HEAD", url, **kwargs)

    def post(self, url, data=None, json=None, **kwargs):
        return self.request("POST", url, data=data, json=json, **kwargs)

    def put(self, url, data=None, **kwargs):
        return self.request("PUT", url, data=data, **kwargs)

    def patch(self, url, data=None, **kwargs):
        return self.request("PATCH", url, data=data, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)


@pytest.fixture
def client_factory(start_wdms_worker_service, no_sub_process_opt):
    if no_sub_process_opt:
        from fastapi.testclient import TestClient
        from wdmsworker.app import app

        @contextmanager
        def make_fastapi_test_client(**kwargs):
            with TestClient(app) as client:
                if "headers" in kwargs:
                    client.headers.update(kwargs["headers"])
                yield client

        return make_fastapi_test_client

    base_url = f"http://127.0.0.1:{start_wdms_worker_service}/api/wdms-worker"

    @contextmanager
    def make_real_client(**kwargs):
        yield TestClientSession(base_url, **kwargs)

    return make_real_client


@pytest.fixture
def test_client_raw(client_factory) -> requests.Session:
    """minimal test client, no predefined headers, only base URL"""
    with client_factory() as client:
        yield client


@pytest.fixture
def data_partition():
    return str(uuid4())[-12:]


@pytest.fixture
def test_client(client_factory, data_partition) -> requests.Session:
    """
    test client, predefined with some predefined headers:
          - data partition
    """
    with client_factory(headers={"data-partition-id": data_partition}) as client:
        yield client
