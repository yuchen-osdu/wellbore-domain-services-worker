#!/usr/bin/env python3
"""Create a deterministic upstream clone with explicitly excluded paths.

GitHub rejects any branch whose reachable history contains a blob over 100 MB.
Some OSDU repositories deleted such files years ago, but the historical blob
still prevents the normal fork_upstream push. This helper removes only paths
listed by a repository administrator, preserving the rest of upstream history.
The same filter must run during initialization and every later upstream sync.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath


def load_excluded_paths(path: Path) -> list[str]:
    """Read and validate repository-relative POSIX paths."""

    excluded: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        candidate = PurePosixPath(value)
        if candidate.is_absolute() or value in {".", ".."} or ".." in candidate.parts:
            raise ValueError(
                f"{path}:{line_number}: excluded path must be repository-relative: {value!r}"
            )
        normalized = candidate.as_posix()
        if normalized not in excluded:
            excluded.append(normalized)
    if not excluded:
        raise ValueError(f"{path}: no upstream history exclusion paths were provided")
    return excluded


def filter_command(repo_dir: Path, excluded_paths: list[str]) -> list[str]:
    """Build the injection-safe git-filter-repo command."""

    command = ["git", "-C", str(repo_dir), "filter-repo", "--force", "--invert-paths"]
    for excluded_path in excluded_paths:
        command.extend(["--path", excluded_path])
    return command


def _run(command: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture_output,
    )


def _rev_parse(repo_dir: Path, ref: str) -> str:
    return _run(
        ["git", "-C", str(repo_dir), "rev-parse", ref],
        capture_output=True,
    ).stdout.strip()


def create_filtered_clone(
    source_url: str,
    branch: str,
    output_dir: Path,
    excluded_paths: list[str],
) -> tuple[str, str]:
    """Clone one upstream branch, remove the configured paths, and return SHAs."""

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    _run(
        [
            "git",
            "clone",
            "--single-branch",
            "--branch",
            branch,
            "--no-tags",
            source_url,
            str(output_dir),
        ]
    )
    original_sha = _rev_parse(output_dir, "HEAD")
    _run(filter_command(output_dir, excluded_paths))
    filtered_sha = _rev_parse(output_dir, "HEAD")
    return original_sha, filtered_sha


def _write_github_output(values: dict[str, str]) -> None:
    output = os.environ.get("GITHUB_OUTPUT", "")
    if not output:
        return
    with Path(output).open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--exclude-paths-file", type=Path, required=True)
    args = parser.parse_args()

    excluded_paths = load_excluded_paths(args.exclude_paths_file)
    original_sha, filtered_sha = create_filtered_clone(
        args.source_url,
        args.branch,
        args.output_dir,
        excluded_paths,
    )
    print(f"Filtered upstream {args.branch}: {original_sha} -> {filtered_sha}")
    for excluded_path in excluded_paths:
        print(f"  excluded from history: {excluded_path}")
    _write_github_output(
        {
            "repo_dir": str(args.output_dir),
            "original_sha": original_sha,
            "filtered_sha": filtered_sha,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
