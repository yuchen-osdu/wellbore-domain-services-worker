#!/usr/bin/env python3
"""Validate the language-specific integration-test runner inputs."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PATH_RE = re.compile(r"^[A-Za-z0-9.][A-Za-z0-9._/-]*$")
EXTRA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$")
UV_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def repository_path(root: Path, value: str, *, kind: str) -> Path:
    """Resolve a validated repository-relative path."""

    if (
        not value
        or value.startswith(("/", "\\"))
        or "\\" in value
        or ".." in value.split("/")
        or not PATH_RE.fullmatch(value)
    ):
        raise ValueError(
            f"{kind} must be a repository-relative path limited to [A-Za-z0-9._/-]"
        )
    resolved = (root / value).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{kind} escapes GITHUB_WORKSPACE") from error
    return resolved


def validate(
    root: Path,
    *,
    test_type: str,
    test_dir: str,
    pytest_runner: str,
    python_version: str,
    uv_version: str,
    python_test_extras: str,
) -> None:
    if test_type not in {"maven", "pytest"}:
        raise ValueError("test_type must be one of: maven, pytest")

    if test_type == "maven":
        directory = Path(test_dir)
        if not directory.is_absolute():
            directory = root / directory
        if not directory.is_dir():
            raise ValueError(
                f"test_dir does not exist or is not a directory: {test_dir}"
            )
        return

    directory = repository_path(root, test_dir, kind="test_dir")
    if not directory.is_dir():
        raise ValueError(f"test_dir does not exist or is not a directory: {test_dir}")

    runner = repository_path(root, pytest_runner, kind="pytest_runner")
    if not runner.is_file() or runner.suffix != ".py":
        raise ValueError(
            f"pytest_runner must name an existing repository-relative .py file: {pytest_runner}"
        )
    if not VERSION_RE.fullmatch(python_version):
        raise ValueError("python_version must be MAJOR.MINOR or MAJOR.MINOR.PATCH")
    if not UV_VERSION_RE.fullmatch(uv_version):
        raise ValueError("uv_version must be X.Y.Z")

    extras = [item.strip() for item in python_test_extras.split(",") if item.strip()]
    if len(extras) != len(set(extras)):
        raise ValueError("python_test_extras must not contain duplicates")
    invalid = [item for item in extras if not EXTRA_RE.fullmatch(item)]
    if invalid:
        raise ValueError(
            "python_test_extras contains an invalid PEP 508 extra name: " + invalid[0]
        )


def main() -> int:
    try:
        validate(
            Path(os.environ["GITHUB_WORKSPACE"]),
            test_type=os.environ.get("TEST_TYPE", ""),
            test_dir=os.environ.get("TEST_DIR", ""),
            pytest_runner=os.environ.get("PYTEST_RUNNER", ""),
            python_version=os.environ.get("PYTHON_VERSION", ""),
            uv_version=os.environ.get("UV_VERSION", ""),
            python_test_extras=os.environ.get("PYTHON_TEST_EXTRAS", ""),
        )
    except (KeyError, ValueError) as error:
        print(f"::error::{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
