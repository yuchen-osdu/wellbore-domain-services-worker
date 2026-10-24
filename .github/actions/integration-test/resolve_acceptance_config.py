#!/usr/bin/env python3
"""Resolve a descriptor acceptance contract against Stack environment facts."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
SERVICE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SECRET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,126}$")
HEALTH_PATH_RE = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")
MAVEN_ARG_RE = re.compile(r"^[^\s\x00-\x1f\x7f]{1,240}$")

EXPECTED_KEYS = {
    "type",
    "path",
    "runnerPath",
    "mavenArguments",
    "rootTokenEnv",
    "noDataAccessTokenEnv",
    "bindings",
    "keyVaultBindings",
    "dependencies",
    "timeoutMinutes",
    "maxAttempts",
}
FACT_SOURCES = {
    "gateway": "GATEWAY_URL",
    "partition": "DATA_PARTITION_ID",
    "entitlementDomain": "ENTITLEMENT_DOMAIN",
    "storageAccount": "STORAGE_ACCOUNT_NAME",
}
RESERVED_ENV_NAMES = {
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "AZURE_CLIENT_ID",
    "AZURE_FEDERATED_TOKEN_FILE",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_TENANT_ID",
    "BASH_ENV",
    "ENV",
    "GITHUB_ENV",
    "GITHUB_OUTPUT",
    "GITHUB_PATH",
    "GITHUB_STEP_SUMMARY",
    "GITHUB_TOKEN",
    "HOME",
    "JAVA_TOOL_OPTIONS",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "MAVEN_OPTS",
    "OLDPWD",
    "PATH",
    "PWD",
    "PYTHONPATH",
    "SHELL",
}
RESERVED_ENV_PREFIXES = ("ACTIONS_", "GITHUB_", "RUNNER_")


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _object(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    return value


def _string(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} contains a control character")
    return value


def _env_name(value: Any, *, field: str) -> str:
    text = _string(value, field=field)
    if not ENV_NAME_RE.fullmatch(text):
        raise ValueError(f"{field} must be an environment variable name")
    if text in RESERVED_ENV_NAMES or text.startswith(RESERVED_ENV_PREFIXES):
        raise ValueError(f"{field} uses a reserved environment variable name")
    return text


def _resolve_bindings(
    bindings: dict[str, Any],
    facts: dict[str, str],
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for env_name, raw_binding in bindings.items():
        _env_name(env_name, field="bindings key")
        binding = _object(raw_binding, field=f"bindings.{env_name}")
        unknown = set(binding) - {"source", "suffix", "value"}
        if unknown:
            raise ValueError(
                f"bindings.{env_name} has unsupported keys: {', '.join(sorted(unknown))}"
            )
        source = _string(binding.get("source"), field=f"bindings.{env_name}.source")
        suffix = _string(binding.get("suffix", ""), field=f"bindings.{env_name}.suffix")
        if source == "literal":
            if "value" not in binding:
                raise ValueError(f"bindings.{env_name}.value is required for source literal")
            value = _string(binding["value"], field=f"bindings.{env_name}.value")
        else:
            if source not in FACT_SOURCES:
                raise ValueError(f"bindings.{env_name}.source is unsupported: {source}")
            if "value" in binding:
                raise ValueError(
                    f"bindings.{env_name}.value is allowed only for source literal"
                )
            fact_name = FACT_SOURCES[source]
            base = facts.get(fact_name, "").strip()
            if not base:
                raise ValueError(
                    f"{fact_name} is required by descriptor binding {env_name}"
                )
            value = base.rstrip("/") if source == "gateway" else base
        resolved[env_name] = value + suffix
    return resolved


def resolve(raw: str, facts: dict[str, str]) -> dict[str, str]:
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"acceptance_config is not valid JSON: {error.msg}") from error
    config = _object(config, field="acceptance_config")
    unknown = set(config) - EXPECTED_KEYS
    if unknown:
        raise ValueError(
            "acceptance_config has unsupported keys: " + ", ".join(sorted(unknown))
        )

    test_type = _string(config.get("type"), field="acceptance_config.type")
    if test_type not in {"maven", "python"}:
        raise ValueError("acceptance_config.type must be one of: maven, python")
    test_dir = _string(config.get("path"), field="acceptance_config.path")
    runner = _string(config.get("runnerPath", ""), field="acceptance_config.runnerPath")
    if test_type == "python" and not runner:
        raise ValueError("acceptance_config.runnerPath is required for Python")
    if test_type == "maven" and runner:
        raise ValueError("acceptance_config.runnerPath is not valid for Maven")

    maven_arguments = config.get(
        "mavenArguments",
        ["verify"] if test_type == "maven" else [],
    )
    if not isinstance(maven_arguments, list):
        raise ValueError("acceptance_config.mavenArguments must be an array")
    if test_type == "maven" and not maven_arguments:
        raise ValueError("acceptance_config.mavenArguments must not be empty for Maven")
    if test_type == "python" and maven_arguments:
        raise ValueError("acceptance_config.mavenArguments is not valid for Python")
    for position, argument in enumerate(maven_arguments):
        if not isinstance(argument, str) or not MAVEN_ARG_RE.fullmatch(argument):
            raise ValueError(
                f"acceptance_config.mavenArguments[{position}] must be one safe argv token"
            )

    root_token_env = _env_name(
        config.get("rootTokenEnv", "ROOT_USER_TOKEN"),
        field="acceptance_config.rootTokenEnv",
    )
    no_data_env = config.get("noDataAccessTokenEnv", "")
    if no_data_env:
        no_data_env = _env_name(
            no_data_env,
            field="acceptance_config.noDataAccessTokenEnv",
        )

    bindings = _object(config.get("bindings", {}), field="acceptance_config.bindings")
    env_map = _resolve_bindings(bindings, facts)

    key_vault_bindings = _object(
        config.get("keyVaultBindings", {}),
        field="acceptance_config.keyVaultBindings",
    )
    for env_name, secret_name in key_vault_bindings.items():
        _env_name(env_name, field="keyVaultBindings key")
        secret = _string(secret_name, field=f"keyVaultBindings.{env_name}")
        if not SECRET_NAME_RE.fullmatch(secret):
            raise ValueError(
                f"keyVaultBindings.{env_name} must be a Key Vault secret name"
            )

    dependencies = _object(
        config.get("dependencies", {}),
        field="acceptance_config.dependencies",
    )
    for service, health_path in dependencies.items():
        if not SERVICE_RE.fullmatch(service):
            raise ValueError(f"dependencies key is not a service slug: {service}")
        path = _string(health_path, field=f"dependencies.{service}")
        if not HEALTH_PATH_RE.fullmatch(path):
            raise ValueError(f"dependencies.{service} must be a gateway path beginning '/'")

    timeout = config.get("timeoutMinutes", 25)
    attempts = config.get("maxAttempts", 2)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 180:
        raise ValueError("acceptance_config.timeoutMinutes must be between 1 and 180")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 5:
        raise ValueError("acceptance_config.maxAttempts must be between 1 and 5")

    return {
        "test_type": test_type,
        "test_dir": test_dir,
        "python_runner": runner,
        "maven_arguments": _compact(maven_arguments),
        "root_token_env": root_token_env,
        "no_data_access_token_env": str(no_data_env),
        "env_map": _compact(env_map),
        "secret_map": _compact(key_vault_bindings),
        "dependencies": _compact(dependencies),
        "timeout_minutes": str(timeout),
        "max_attempts": str(attempts),
    }


def main() -> int:
    try:
        outputs = resolve(
            os.environ.get("ACCEPTANCE_CONFIG", ""),
            {name: os.environ.get(name, "") for name in FACT_SOURCES.values()},
        )
        output_path = Path(os.environ["GITHUB_OUTPUT"])
        with output_path.open("a", encoding="utf-8") as stream:
            for name, value in outputs.items():
                stream.write(f"{name}={value}\n")
    except (KeyError, ValueError) as error:
        print(f"::error::{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
