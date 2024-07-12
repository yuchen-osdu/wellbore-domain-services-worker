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


@pytest.mark.parametrize(
    "use_token,expected_status_code,expected_response",
    [
        (True, 404, ""),  # response is empty and should not contain "Not found"
        (False, 403, "RBAC: access denied"),  # since recently, without token requests return 403 error
    ],
)
@pytest.mark.parametrize("path", ["docs", "openapi.json", "about", "healthz", "data/unknown-record-id/unknown-id"])
def test_service_not_reachable_externally(
    base_url, check_cert, token, path, use_token, expected_status_code, expected_response
):
    """
    Test Worker service is not accessible from outside the cluster with or without a valid token.
    """
    url = f"{base_url}/{path}"
    headers = {"data-partition-id": "opendes"}  # prevent 422 error because of missing data partition.

    if use_token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.request("GET", url, headers=headers, verify=check_cert)
    assert response.status_code == expected_status_code, (
        "Worker service should NOT be available from out of the " "cluster"
    )
    assert response.text in expected_response, f"Response '{response.text}' should contains '{expected_response}'"
