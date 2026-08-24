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

import pytest
import requests


@pytest.mark.parametrize(
    "use_token,expected_status_codes,expected_response",
    [
        (True, {404}, ""),  # response is empty and should not contain "Not found"
        # ADME routes the path and rejects anonymously at RBAC (403); SPI does not
        # publish the worker route at all (404). Both satisfy the external-isolation
        # contract this test owns.
        (False, {403, 404}, "RBAC: access denied"),
    ],
)
@pytest.mark.parametrize("path", ["docs", "openapi.json", "about", "healthz", "data/unknown-record-id/unknown-id"])
def test_service_not_reachable_externally(
    base_url, check_cert, token, path, use_token, expected_status_codes, expected_response
):
    """
    Test Worker service is not accessible from outside the cluster with or without a valid token.
    """
    url = f"{base_url}/{path}"
    headers = {"data-partition-id": "opendes"}  # prevent 422 error because of missing data partition.

    if use_token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.request("GET", url, headers=headers, verify=check_cert)
    assert response.status_code in expected_status_codes, (
        "Worker service should NOT be available from out of the cluster"
    )
    if response.status_code == 403:
        assert expected_response in response.text, f"Response '{response.text}' should contain '{expected_response}'"
    else:
        assert response.text == "", f"Expected an empty 404 response, got '{response.text}'"
