#!/usr/bin/env python3
"""Delegated runner for the Wellbore worker acceptance suites.

This is the ADME two-suite runner contract adapted to work from either a
checked-out repository or `/app/testing`. SPI supplies `TEST_REPO_ROOT`,
`TEST_RESULTS_DIR`, and the deployed-worker environment.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.stderr.write(f"ERROR: required environment variable {name} is not set\n")
        raise SystemExit(2)
    return value


def main() -> None:
    repo_root = Path(os.environ.get("TEST_REPO_ROOT", DEFAULT_REPO_ROOT)).resolve()
    os.chdir(repo_root)

    results_dir = Path(os.environ.get("TEST_RESULTS_DIR", repo_root / "test-reports")).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)
    python = sys.executable

    service_rc = subprocess.run(
        [
            python,
            "-m",
            "pytest",
            "./tests/service",
            f"--junitxml={results_dir / 'service_tests_report.xml'}",
            "-o",
            "junit_suite_name=wdms_worker_service",
        ],
        check=False,
    ).returncode

    token = _require("INTEGRATION_TESTER_ACCESS_TOKEN")
    worker_host = _require("WDMS_WORKER_HOST")
    check_cert = os.environ.get("WDMS_WORKER_CHECK_CERT", "true")

    security_rc = subprocess.run(
        [
            python,
            "-m",
            "pytest",
            "./tests/security/test_authorization.py",
            "--base_url",
            worker_host,
            "--check_cert",
            check_cert,
            "--token",
            token,
            f"--junitxml={results_dir / 'security_tests_report.xml'}",
            "-o",
            "junit_suite_name=wdms_worker_security",
        ],
        check=False,
    ).returncode

    raise SystemExit(service_rc or security_rc)


if __name__ == "__main__":
    main()
