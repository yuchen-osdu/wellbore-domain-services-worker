from __future__ import annotations

import io
import os
import time
import uuid
from typing import Any

import pandas as pd
import pytest
import requests


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is not set: {name}")
    return value


def _access_token() -> str:
    return os.environ.get("ROOT_USER_TOKEN") or _required_environment("INTEGRATION_TESTER_ACCESS_TOKEN")


def _base_headers(content_type: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_access_token()}",
        "data-partition-id": _required_environment("DATA_PARTITION"),
        "accept": "application/json",
        "correlation-id": f"spi-wdms-worker-{uuid.uuid4()}",
    }
    if content_type:
        headers["content-type"] = content_type
    return headers


def _gateway_url() -> str:
    return _required_environment("GATEWAY_URL").rstrip("/")


def _wellbore_url() -> str:
    return os.environ.get(
        "WELLBORE_BASE_URL",
        f"{_gateway_url()}/api/os-wellbore-ddms",
    ).rstrip("/")


def _require_status(response: requests.Response, expected: set[int]) -> None:
    if response.status_code not in expected:
        pytest.fail(
            f"{response.request.method} {response.request.url} returned "
            f"HTTP {response.status_code}: {response.text[:1000]}"
        )


def _ensure_legal_tag() -> str:
    partition = _required_environment("DATA_PARTITION")
    legal_tag = os.environ.get("LEGAL_TAG", f"{partition}-wdms-ci")
    legal_api = f"{_gateway_url()}/api/legal/v1/legaltags"
    headers = _base_headers()

    response = requests.get(f"{legal_api}/{legal_tag}", headers=headers, timeout=30)
    if response.status_code == 200:
        return legal_tag
    _require_status(response, {404})

    prefix = f"{partition}-"
    short_name = legal_tag.removeprefix(prefix)
    response = requests.post(
        legal_api,
        headers={**headers, "content-type": "application/json"},
        json={
            "name": short_name,
            "description": "Legal tag for SPI Wellbore worker live acceptance tests",
            "properties": {
                "countryOfOrigin": ["US"],
                "contractId": "SPI-WDMS-CI",
                "expirationDate": "2099-12-31",
                "dataType": "Public Domain Data",
                "originator": "OSDU",
                "securityClassification": "Public",
                "exportClassification": "EAR99",
                "personalData": "No Personal Data",
            },
        },
        timeout=30,
    )
    _require_status(response, {200, 201, 409})
    return legal_tag


def _welllog_record(legal_tag: str, dataframe: pd.DataFrame) -> dict[str, Any]:
    partition = _required_environment("DATA_PARTITION")
    acl_domain = _required_environment("ACL_DOMAIN")
    return {
        "acl": {
            "owners": [f"data.default.owners@{partition}.{acl_domain}"],
            "viewers": [f"data.default.viewers@{partition}.{acl_domain}"],
        },
        "legal": {
            "legaltags": [legal_tag],
            "otherRelevantDataCountries": ["US"],
        },
        "kind": "osdu:wks:work-product-component--WellLog:1.2.0",
        "data": {
            "Source": "spi_wdms_worker_acceptance",
            "Curves": [{"CurveID": column, "NumberOfColumns": 1} for column in dataframe.columns],
            "ReferenceCurveID": dataframe.columns[0],
        },
        "meta": [],
    }


def test_candidate_worker_handles_bulk_round_trip_and_statistics():
    version = requests.get(
        f"{_wellbore_url()}/version",
        headers=_base_headers(),
        timeout=30,
    )
    _require_status(version, {200})
    details = version.json()["details"]
    assert details["bulk_backend"] == "Bulk worker service"
    assert str(details["enable_wdms_bulk_worker"]).lower() == "true"

    legal_tag = _ensure_legal_tag()
    dataframe = pd.DataFrame(
        {
            "MD": [float(value) for value in range(20)],
            "GR": [float(value * 2) for value in range(20)],
            "RHOB": [2.0 + value / 100 for value in range(20)],
        }
    )
    record_id = ""
    try:
        response = requests.post(
            f"{_wellbore_url()}/ddms/v3/welllogs",
            headers=_base_headers("application/json"),
            json=[_welllog_record(legal_tag, dataframe)],
            timeout=60,
        )
        _require_status(response, {200})
        record_id = response.json()["recordIds"][0]

        response = requests.post(
            f"{_wellbore_url()}/ddms/v3/welllogs/{record_id}/data",
            headers=_base_headers("application/x-parquet"),
            data=dataframe.to_parquet(engine="pyarrow"),
            timeout=90,
        )
        _require_status(response, {200})
        record_version = response.json()["recordIdVersions"][0].rsplit(":", 1)[-1]

        response = requests.get(
            f"{_wellbore_url()}/ddms/v3/welllogs/{record_id}/data",
            headers={**_base_headers(), "accept": "application/x-parquet"},
            timeout=90,
        )
        _require_status(response, {200})
        actual = pd.read_parquet(io.BytesIO(response.content))
        pd.testing.assert_frame_equal(
            actual.reset_index(drop=True),
            dataframe.reset_index(drop=True),
            check_dtype=False,
        )

        response = requests.post(
            f"{_wellbore_url()}/ddms/v3/welllogs/{record_id}/versions/{record_version}/data/statistics",
            headers=_base_headers(),
            timeout=60,
        )
        _require_status(response, {200})

        statistics = None
        last_statistics_response = None
        for delay in (5, 10, 15, 30):
            time.sleep(delay)
            response = requests.get(
                f"{_wellbore_url()}/ddms/v3/welllogs/{record_id}/data/statistics",
                headers=_base_headers(),
                timeout=60,
            )
            last_statistics_response = response
            if response.status_code == 200:
                statistics = response.json()["data"]
                break

        assert statistics is not None, (
            "Worker statistics did not complete within 60 seconds; "
            f"last response was HTTP {last_statistics_response.status_code}: "
            f"{last_statistics_response.text[:1000]}"
        )
        assert int(float(statistics["MD"]["totalCount"])) == 20
        assert int(float(statistics["GR"]["nonAbsentValuesCount"])) == 20
    finally:
        if record_id:
            response = requests.delete(
                f"{_wellbore_url()}/ddms/v3/welllogs/{record_id}?purge=true",
                headers=_base_headers(),
                timeout=60,
            )
            _require_status(response, {200, 204})
