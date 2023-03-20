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

import requests
import pytest


@pytest.mark.parametrize("use_token", [True, False])
@pytest.mark.parametrize("path", ["docs", "openapi.json", "about", "healthz", "data/unknown-record-id/unknown-id"])
def test_service_not_reachable_externally(base_url, check_cert, token, path, use_token):
    """
    Test Worker service is not accessible from outside the cluster with or without a valid token.
    """
    url = f"{base_url}/{path}"
    headers = {"data-partition-id": "opendes"}  # prevent 422 error because of missing data partition.

    if use_token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.request("GET", url, headers=headers, verify=check_cert)
    assert response.status_code == 404, "Worker service should NOT be available from out of the cluster"
    assert response.text == str(), "Response should be empty, because service was not reached"
