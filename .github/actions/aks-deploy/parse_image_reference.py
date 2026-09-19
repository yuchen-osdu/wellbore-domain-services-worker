#!/usr/bin/env python3
"""Validate and split an immutable container image reference."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


IMAGE_RE = re.compile(
    r"^(?P<repository>[^@\s]+)@(?P<digest>sha256:[a-f0-9]{64})$"
)


def parse_image_reference(image: str) -> tuple[str, str]:
    match = IMAGE_RE.fullmatch(image)
    if not match:
        raise ValueError(
            f"image must match <repository>@sha256:<64-hex> (got: {image!r})"
        )
    return match.group("repository"), match.group("digest")


def write_outputs(image: str, repository: str, digest: str) -> None:
    values = (
        f"image={image}\n"
        f"repository={repository}\n"
        f"digest={digest}\n"
    )
    output = os.environ.get("GITHUB_OUTPUT", "")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(values)
    else:
        print(values, end="")


def main() -> int:
    image = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        repository, digest = parse_image_reference(image)
    except ValueError as error:
        print(f"::error::{error}")
        return 1
    write_outputs(image, repository, digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
