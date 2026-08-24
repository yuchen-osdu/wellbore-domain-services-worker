#!/usr/bin/env python3
"""Run the SPI live worker acceptance test through the public WDMS API."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is not set: {name}")
    return value


def _pytest_command(junit_xml: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        str(REPOSITORY_ROOT / "tests" / "acceptance"),
        "-p",
        "no:randomly",
        f"--junitxml={junit_xml}",
    ]


def run(junit_xml: Path) -> int:
    _required_environment("GATEWAY_URL")
    _required_environment("DATA_PARTITION")
    _required_environment("ACL_DOMAIN")
    if not (os.environ.get("ROOT_USER_TOKEN") or os.environ.get("INTEGRATION_TESTER_ACCESS_TOKEN")):
        raise RuntimeError("ROOT_USER_TOKEN or INTEGRATION_TESTER_ACCESS_TOKEN must be set")

    junit_xml.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        _pytest_command(junit_xml),
        cwd=REPOSITORY_ROOT,
        check=False,
    ).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit-xml", required=True, type=Path)
    args = parser.parse_args()
    try:
        return run(args.junit_xml.resolve())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"SPI WDMS worker acceptance runner failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
