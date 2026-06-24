# Pollen integration tests

These exercise the **real** Pollen upload client against the **real** backend
lambda and a **real** S3 multipart lifecycle — nothing is mocked. They cover the
contract the unit tests can only fake: single presigned PUT, multipart assembly,
resume-after-interruption, recovery from a reaped upload, device-scope
enforcement, and API-key auth.

```
Pollen Presigner ──HTTP──▶ Flask gateway ──▶ handler.lambda_handler
                                                │  routing + auth + dispatch
                                                │  boto3
                                                ▼
Pollen Uploader ──presigned PUT / upload_part──▶ ministack S3
```

The Flask gateway (`conftest.py`) turns each request into an API Gateway (HTTP
API v2) event and drives `handler.lambda_handler` in `sensing-garden-backend`, so
routing, `x-api-key` auth, and device-scoped dispatch all run exactly as in
production — not just the leaf handler functions. A device API key is seeded into
DynamoDB and resolved by the real auth path. S3 **and** DynamoDB are served by
[ministack](https://pypi.org/project/ministack/), an in-process AWS emulator.

## Trigger lambda (`test_trigger_archive.py`)

A second suite drives the **trigger lambda** that indexes hourly archives. A tar
is uploaded to ministack S3, then `trigger_handler.lambda_handler` processes it
end to end — reading the archive from S3, writing track/classification rows to
DynamoDB stamped with archive byte ranges, and recording idempotency in the
processed-objects table so a re-delivery is skipped. (`trigger/src` and
`lambda/src` share top-level module names, so the trigger is imported with those
names isolated; see the `trigger` fixture.)

## Requirements

1. **ministack + boto3** — installed via the `integration` dependency group:
   ```bash
   poetry install --with integration
   ```
   The fixtures auto-start ministack if the `ministack` binary is on `PATH`;
   otherwise point them at a running instance with `MINISTACK_ENDPOINT`
   (default `http://localhost:4566`).

2. **A sensing-garden-backend checkout** — found automatically when it sits as a
   sibling of this repo (`../sensing-garden-backend`), or set `SG_BACKEND_SRC` to
   its `lambda/src` directory.

If either is missing the whole suite skips cleanly.

## Running

```bash
# from the repo root
poetry run pytest tests/integration -v

# or against an explicit backend checkout / ministack
SG_BACKEND_SRC=/path/to/sensing-garden-backend/lambda/src \
MINISTACK_ENDPOINT=http://localhost:4566 \
    poetry run pytest tests/integration -v
```

All integration tests are marked `@pytest.mark.integration`, so the default
unit-test run is unaffected; deselect them with `-m "not integration"`.
