#!/bin/bash
# Regenerate requirements.txt / requirements_dev.txt from uv.lock.
#
# uv.lock (resolved from pyproject.toml) is the source of truth. These flat
# requirements files are generated exports kept for compatibility with plain
# `pip install -r` consumers (local installs, dependency scanning). Do not
# hand-edit them; run this script after changing dependencies in pyproject.toml.
set -euo pipefail

cd "$(dirname "$0")/.."

INDEX_URL="https://community.opengroup.org/api/v4/projects/465/packages/pypi/simple"

# Keep the lockfile in sync with pyproject before exporting.
uv lock

# The private OSDU index is configured in pyproject's [[tool.uv.index]], so uv
# does not emit it. Prepend it so plain `pip install -r` consumers can still
# resolve the OSDU packages.
gen() {
  local out="$1"; shift
  {
    echo "--extra-index-url ${INDEX_URL}"
    uv export --locked --no-hashes --no-emit-project "$@" --format requirements-txt
  } > "${out}"
  echo "wrote ${out}"
}

gen requirements.txt
gen requirements_dev.txt --extra dev
