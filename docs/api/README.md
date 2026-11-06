# Wellbore worker OpenAPI specification

The OpenAPI specification is generated from the FastAPI application. The service
serves it as JSON at `/openapi.json`.

The committed baseline is [`community/v1/openapi.json`](community/v1/openapi.json).
JSON is used for both the baseline and the live endpoint, so the shared CIMPL
OpenAPI check can compare them without format conversion or a service-local job
override. The live route is `/api/wdms-worker/openapi.json`.

The `v1` directory is the shared CI job's default documentation location, not
a version of the worker API.

## Updating the baseline

From the repository root, with development dependencies installed:

```bash
uv run --frozen --no-sync python -m pytest tests/unit/spec/
```

When the schema changes, `test_api_spec` writes the updated JSON and fails.
Review and commit that file, then rerun the tests. The output uses sorted keys
and two-space indentation. The test adds the relative `servers` URL from
`API_PREFIX` (`/api/wdms-worker`), which FastAPI normally adds on the first
HTTP request.

The unit tests are the pre-merge check. The shared CIMPL job compares the
committed baseline with the deployed service after deployment.
