"""Fixtures for Pollen integration tests.

These wire the *real* Pollen upload client to the *real* backend presign
handlers and a *real* S3 multipart lifecycle served by ministack:

    Pollen Presigner --HTTP--> Flask shim --> backend route handlers
                                                  |  boto3
                                                  v
    Pollen Uploader  --presigned PUT/upload_part-----> ministack S3

Nothing is mocked. The shim is a thin HTTP front for the backend handlers
(the same code API Gateway invokes), with a fixed authenticated device.

Requirements (the whole module skips cleanly if either is missing):
  * ministack on http://localhost:4566 (override with MINISTACK_ENDPOINT);
    started automatically if the `ministack` binary is on PATH.
  * a sensing-garden-backend checkout: sibling of this repo, or SG_BACKEND_SRC.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

# ministack must back S3 *and* DynamoDB (the /upload-url handler records an
# activity event). Set the endpoint env before any backend module is imported,
# since backend boto3 clients are created at import time.
MINISTACK_ENDPOINT = os.environ.get("MINISTACK_ENDPOINT", "http://localhost:4566")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ENDPOINT_URL", MINISTACK_ENDPOINT)
os.environ.setdefault("AWS_ENDPOINT_URL_S3", MINISTACK_ENDPOINT)

OUTPUT_BUCKET = "scl-sensing-garden"
ACTIVITY_TABLE = os.environ.get("ACTIVITY_EVENTS_TABLE", "sensing-garden-activity-events")
DEVICE_API_KEYS_TABLE = os.environ.get("DEVICE_API_KEYS_TABLE", "sensing-garden-device-api-keys")
DEVICE = {"device_id": "FLIK2", "dot_ids": ["dot1"]}
# The device authenticates with this key; it is seeded into DynamoDB and resolved
# by the real auth path (auth.authenticate_api_key -> get_active_device_api_key).
DEVICE_API_KEY = "integration-device-key"

# Tables the trigger lambda writes when indexing an archive.
TRACKS_TABLE = "sensing-garden-tracks"
CLASSIFICATIONS_TABLE = "sensing-garden-classifications"
DEVICES_TABLE = "sensing-garden-devices"
PROCESSED_OBJECTS_TABLE = "sensing-garden-s3-processed-objects"
# The trigger reads these at import time.
os.environ.setdefault("OUTPUT_BUCKET", OUTPUT_BUCKET)
os.environ.setdefault("PROCESSED_OBJECTS_TABLE", PROCESSED_OBJECTS_TABLE)


def _port_open(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.2)
    return False


def _find_backend_src() -> Path | None:
    candidates = []
    env = os.environ.get("SG_BACKEND_SRC")
    if env:
        candidates.append(Path(env))
    repo_root = Path(__file__).resolve().parents[2]
    candidates.append(repo_root.parent / "sensing-garden-backend" / "lambda" / "src")
    for path in candidates:
        if (path / "routes" / "multipart.py").exists():
            return path
    return None


@pytest.fixture(scope="session")
def ministack_endpoint() -> str:
    """Ensure a ministack server is reachable, starting one if we can."""
    parsed = urlparse(MINISTACK_ENDPOINT)
    host, port = parsed.hostname or "localhost", parsed.port or 4566

    if _port_open(host, port):
        yield MINISTACK_ENDPOINT
        return

    binary = shutil.which("ministack")
    if not binary:
        pytest.skip(f"ministack not reachable at {MINISTACK_ENDPOINT} and not on PATH")

    env = {**os.environ, "GATEWAY_PORT": str(port)}
    proc = subprocess.Popen([binary, "-d"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.wait(timeout=30)
    if not _wait_for_port(host, port):
        pytest.skip(f"ministack did not come up on {host}:{port}")
    try:
        yield MINISTACK_ENDPOINT
    finally:
        subprocess.run([binary, "--stop"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.fixture(scope="session")
def s3(ministack_endpoint):
    """A boto3 S3 client bound to ministack, with the output bucket created."""
    boto3 = pytest.importorskip("boto3")
    from botocore.config import Config

    client = boto3.client("s3", endpoint_url=ministack_endpoint, config=Config(signature_version="s3v4"))
    try:
        client.create_bucket(Bucket=OUTPUT_BUCKET)
    except client.exceptions.ClientError:
        pass  # already exists across runs

    # DynamoDB tables the real lambda path touches: the activity log (written by
    # /upload-url) and the device-api-keys table (read by auth to resolve the
    # device behind the request).
    ddb = boto3.client("dynamodb", endpoint_url=ministack_endpoint)
    try:
        ddb.create_table(
            TableName=ACTIVITY_TABLE,
            AttributeDefinitions=[
                {"AttributeName": "event_date", "AttributeType": "S"},
                {"AttributeName": "timestamp_event_id", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "event_date", "KeyType": "HASH"},
                {"AttributeName": "timestamp_event_id", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except ddb.exceptions.ClientError:
        pass
    try:
        ddb.create_table(
            TableName=DEVICE_API_KEYS_TABLE,
            AttributeDefinitions=[
                {"AttributeName": "device_id", "AttributeType": "S"},
                {"AttributeName": "api_key", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "device_id", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "api_key_index",
                    "KeySchema": [{"AttributeName": "api_key", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except ddb.exceptions.ClientError:
        pass
    boto3.resource("dynamodb", endpoint_url=ministack_endpoint).Table(DEVICE_API_KEYS_TABLE).put_item(
        Item={
            "device_id": DEVICE["device_id"],
            "api_key": DEVICE_API_KEY,
            "dot_ids": DEVICE["dot_ids"],
            "created": "2026-01-01T00:00:00+00:00",
            "status": "active",
        }
    )
    return client


@pytest.fixture(scope="session")
def dynamodb_resource(ministack_endpoint):
    boto3 = pytest.importorskip("boto3")
    return boto3.resource("dynamodb", endpoint_url=ministack_endpoint)


@pytest.fixture(scope="session")
def trigger_tables(dynamodb_resource):
    """Create the DynamoDB tables the trigger writes (idempotent)."""
    client = dynamodb_resource.meta.client

    def _create(name, key_schema, attrs):
        try:
            client.create_table(
                TableName=name,
                KeySchema=key_schema,
                AttributeDefinitions=attrs,
                BillingMode="PAY_PER_REQUEST",
            )
        except client.exceptions.ResourceInUseException:
            pass

    _create(
        TRACKS_TABLE,
        [{"AttributeName": "track_id", "KeyType": "HASH"}, {"AttributeName": "device_id", "KeyType": "RANGE"}],
        [{"AttributeName": "track_id", "AttributeType": "S"}, {"AttributeName": "device_id", "AttributeType": "S"}],
    )
    _create(
        CLASSIFICATIONS_TABLE,
        [{"AttributeName": "device_id", "KeyType": "HASH"}, {"AttributeName": "timestamp", "KeyType": "RANGE"}],
        [{"AttributeName": "device_id", "AttributeType": "S"}, {"AttributeName": "timestamp", "AttributeType": "S"}],
    )
    _create(DEVICES_TABLE, [{"AttributeName": "device_id", "KeyType": "HASH"}],
            [{"AttributeName": "device_id", "AttributeType": "S"}])
    _create(PROCESSED_OBJECTS_TABLE, [{"AttributeName": "object_id", "KeyType": "HASH"}],
            [{"AttributeName": "object_id", "AttributeType": "S"}])


@pytest.fixture(scope="session")
def trigger(ministack_endpoint):
    """Import the real trigger lambda.

    trigger/src and lambda/src both expose top-level modules named activity,
    schemas and composites, so we import trigger_handler with those names cleared
    (it binds its own copies), then restore the previous modules so the API
    handler path is left untouched.
    """
    src = _find_backend_src()
    if src is None:
        pytest.skip("sensing-garden-backend src not found (set SG_BACKEND_SRC or check out as a sibling repo)")
    trigger_src = src.parent.parent / "trigger" / "src"
    if not (trigger_src / "trigger_handler.py").exists():
        pytest.skip("trigger/src not found in sensing-garden-backend")

    names = ("activity", "schemas", "composites", "composite_repair", "local_parse_check", "trigger_handler")
    saved = {name: sys.modules.get(name) for name in names}
    for name in names:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(trigger_src))
    try:
        import trigger_handler as th  # noqa: E402
    finally:
        try:
            sys.path.remove(str(trigger_src))
        except ValueError:
            pass
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module
            else:
                sys.modules.pop(name, None)
    return th


@pytest.fixture(scope="session")
def _backend(ministack_endpoint):
    """Import the real backend lambda entrypoint (skip if not checked out)."""
    src = _find_backend_src()
    if src is None:
        pytest.skip("sensing-garden-backend src not found (set SG_BACKEND_SRC or check out as a sibling repo)")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import handler  # noqa: E402  (env/path set above)

    return handler


@pytest.fixture(scope="session")
def presign_url(_backend, s3):
    """Run a Flask gateway that drives the real lambda entrypoint.

    Each request is turned into an API Gateway (HTTP API v2) event and passed to
    handler.lambda_handler, so routing, API-key auth, and device-scoped dispatch
    all run exactly as in production -- not just the leaf handler functions.
    """
    flask = pytest.importorskip("flask")
    from werkzeug.serving import make_server

    lambda_handler = _backend.lambda_handler

    app = flask.Flask("pollen-api-gateway")

    @app.route("/<path:subpath>", methods=["POST", "GET"])
    def _gateway(subpath):
        event = {
            "requestContext": {"http": {"method": flask.request.method, "path": f"/{subpath}"}},
            "headers": {k: v for k, v in flask.request.headers.items()},
            "body": flask.request.get_data(as_text=True),
        }
        result = lambda_handler(event, None)
        return flask.Response(
            result.get("body", ""),
            status=result["statusCode"],
            mimetype="application/json",
        )

    server = make_server("127.0.0.1", 0, app, threaded=True)
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def presigner(presign_url):
    from bugcam.pollen.presign import Presigner

    return Presigner(presign_url, DEVICE_API_KEY)


@pytest.fixture
def output_bucket():
    return OUTPUT_BUCKET


@pytest.fixture
def device_api_key():
    return DEVICE_API_KEY


@pytest.fixture
def tracks_table(dynamodb_resource):
    return dynamodb_resource.Table(TRACKS_TABLE)


@pytest.fixture
def classifications_table(dynamodb_resource):
    return dynamodb_resource.Table(CLASSIFICATIONS_TABLE)


@pytest.fixture
def s3_key():
    """A unique, in-scope key per test so tests never collide in the bucket."""
    return f"v2/archives/{DEVICE['device_id']}/{uuid.uuid4().hex}.tar"


@pytest.fixture
def fetch_object(s3):
    def _fetch(key: str) -> bytes:
        return s3.get_object(Bucket=OUTPUT_BUCKET, Key=key)["Body"].read()

    return _fetch
