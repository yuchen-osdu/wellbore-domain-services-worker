# Service Configuration (`service-config`)

Template-owned tooling for the fork-owned service descriptor `.spi/service.yaml`
([ADR-039](../../../doc/src/adr/039-fork-owned-service-descriptor.md)).

This directory is synced to every fork by template-sync. Forks do not edit it; they edit
`.spi/service.yaml`, which template-sync never touches.

| File | Purpose |
| --- | --- |
| `schema.json` | Schema version 2: closed archetypes plus the acceptance-test data contract |
| `descriptor.py` | Strict standard-library parser (YAML subset), validator and resolver |
| `read_service_config.py` | Workflow/settings entry point: emits the `read-service-config` output contract or JSON |
| `generate_descriptor.py` | Initialization detection and generation; halts on ambiguous/unsupported repositories |
| `generate_codeowners.py` | Seeds or verifies the `/.spi/` CODEOWNERS rule |

## Why a checked-in parser

GitHub-hosted runners guarantee a standard-library `python3`, not PyYAML or `yq`. The parser
accepts only what a descriptor needs — block mappings, scalar sequences, single-line flow
sequences, quoted/plain scalars, booleans and integers — and rejects anchors, aliases, tags, block
scalars, multiple documents, tabs and nulls. Parsing is therefore deterministic, dependency-free
and fails closed on anything unusual.

## Output contract

`read_service_config.py --format github` writes exactly these keys and nothing else:

```text
descriptor_present  schema_version  archetype     service_name  dockerfile_profile
unit_test_type      has_coverage    build_lane    lane_implemented  fallback
python_runtime_version  python_compatibility_versions  python_compatibility_matrix
python_distribution  python_import_package  python_test_extras  python_runtime_extras
python_unit_test_path  python_service_in_process_test_path
python_service_subprocess_test_path  python_acceptance_test_path
python_acceptance_runner_path  app_module  acceptance_config  java_maven_profiles
service_target_jar
```

`acceptance_config` is either empty or deterministic compact JSON. It always contains
`type`, `path`, `runnerPath`, `mavenArguments`, `rootTokenEnv`,
`noDataAccessTokenEnv`, `bindings`, `keyVaultBindings`, `dependencies`,
`timeoutMinutes` and `maxAttempts`, with defaults normalized. `java_maven_profiles`
is the comma-joined `build.mavenProfiles`; `service_target_jar` is the safe
repository-relative `build.artifact.path` glob.

Job outputs never carry shell commands or secret values. Maven arguments remain a JSON argv list,
and a Python acceptance runner remains a schema-validated repository-relative `.py` path. Binding
and Key Vault maps contain environment variable names, approved runtime sources, and Key Vault
secret *names* only. Consumers must decode the JSON and invoke tools directly, never evaluate
descriptor text as shell. Environment identifiers cannot replace protected process, GitHub
Actions, runner, OIDC, Azure identity, language-tooling or shell variables; all `GITHUB_`,
`RUNNER_` and `ACTIONS_` names are reserved.

## Schema version 2 examples

Java/Maven:

```yaml
schemaVersion: 2
service:
  name: legal
  archetype: java-maven-azure
build:
  mavenProfiles: [core, azure]
  artifact:
    path: "**/target/*-spring-boot.jar"
tests:
  acceptance:
    type: maven
    path: testing/integration-tests
    mavenArguments:
      - -pl
      - legal-test-azure
      - -am
      - verify
      - -DfailIfNoTests=false
      - -Dtest=!Class#method,!Other#method
    bindings:
      LEGAL_HOST:
        source: gateway
        suffix: /api/legal/v1
    keyVaultBindings:
      CLIENT_SECRET: acceptance-client-secret
    dependencies:
      entitlements: /api/entitlements/v2/_ah/readiness_check
```

Python:

```yaml
schemaVersion: 2
service:
  name: wellbore-ddms-worker
  archetype: python-uv-fastapi
tests:
  acceptance:
    type: python
    path: tests/acceptance
    runnerPath: .spi/run_acceptance.py
    rootTokenEnv: ROOT_USER_TOKEN
    noDataAccessTokenEnv: NO_DATA_ACCESS_TOKEN
    timeoutMinutes: 25
    maxAttempts: 2
    bindings:
      PARTITION_ID:
        source: literal
        value: opendes
container:
  appModule: wdmsworker.app:app
```

`schemaVersion: 1` remains build-compatible for existing services, but validation reports a
deprecation warning and newly generated descriptors use version 2.

Exit codes: `0` when the descriptor is valid or absent, `1` when a present descriptor is invalid
(the required `🐳 Docker Build` check then fails closed).

## Usage

```bash
# Resolve for workflows
python3 read_service_config.py --root . --service-name partition \
  --format github --output "$GITHUB_OUTPUT" --summary "$GITHUB_STEP_SUMMARY"

# Machine-readable, value-free diagnostics (used by settings-apply)
python3 read_service_config.py --root . --format json --redact

# Initialization
python3 generate_descriptor.py --root . --service-name partition
python3 generate_codeowners.py --path CODEOWNERS --owners "@my-org/engineering-system"
```

## Adding an archetype

1. Add the archetype to `schema.json` with its `lane`, `laneImplemented` flag and defaults.
2. Add the statically declared build job to `build.yml` and `validate.yml` (expressions are not
   allowed in `uses:`), gated on `needs.read-service-config.outputs.build_lane`.
3. Add the lane to `docker-build-required`'s `needs` so the required check reflects it.
4. Extend `generate_descriptor.py` detection and the tests under `tests/`.

Until step 2 exists, a descriptor declaring that archetype fails the required check closed —
never a green skip.
