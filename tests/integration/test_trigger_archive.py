"""The trigger lambda indexing an hourly archive into DynamoDB, on ministack.

A tar archive is uploaded to ministack S3, then the real trigger lambda
(handler -> S3 read -> DynamoDB writes -> idempotency store) processes it. We
assert the rows land in DynamoDB, carry the archive byte ranges, and that a
re-delivery is skipped via the processed-objects table.
"""
from __future__ import annotations

import io
import json
import tarfile
import uuid

import pytest

# Optional deps used only by this integration test; skip the module cleanly at
# collection when they're absent (e.g. the unit CI run that deselects integration).
Key = pytest.importorskip("boto3.dynamodb.conditions").Key
Image = pytest.importorskip("PIL.Image")

pytestmark = pytest.mark.integration

_PRED = {
    "family": "Family", "genus": "Genus", "species": "Species",
    "family_confidence": 0.9, "genus_confidence": 0.8, "species_confidence": 0.7,
}


def _jpeg(color: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color).save(buf, format="JPEG")
    return buf.getvalue()


def _make_tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:  # uncompressed -> stable offsets
        for name, body in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def _archive(device: str):
    date = "20260412"
    prefix = f"v1/{device}/{date}"
    crop_key = f"{prefix}/crops/12224_163315/frame_000000.jpg"
    composite_key = f"{prefix}/composites/12224_163315.jpg"
    results_key = f"{prefix}/results.json"
    results = json.dumps({
        "source_device": device,
        "date": date,
        "tracks": [{
            "track_id": "12224",
            "timestamp": "163315",
            "final_prediction": _PRED,
            "num_detections": 1,
            "frames": [{"frame_number": 0, "prediction": _PRED, "bbox": [1.0, 2.0, 3.0, 4.0]}],
        }],
    }).encode("utf-8")
    composite_bytes = _jpeg("blue")
    # Device supplies the composite, so it stays in the tar (no PIL generation).
    members = {crop_key: _jpeg("red"), composite_key: composite_bytes, results_key: results}
    return crop_key, composite_key, composite_bytes, _make_tar(members)


def _event(bucket: str, key: str, etag: str):
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key, "eTag": etag.strip('"')}}}]}


def test_archive_indexed_into_dynamodb(
    trigger, s3, output_bucket, trigger_tables, tracks_table, classifications_table
):
    device = f"FLIK2-{uuid.uuid4().hex[:8]}"
    crop_key, composite_key, composite_bytes, tar = _archive(device)
    archive_key = f"v2/archives/{device}/20260412_160000.tar"
    etag = s3.put_object(Bucket=output_bucket, Key=archive_key, Body=tar)["ETag"]

    resp = trigger.lambda_handler(_event(output_bucket, archive_key, etag), None)
    assert resp["statusCode"] == 200
    summary = json.loads(resp["body"])["processed"][0]
    assert summary.get("archives") == 1
    assert summary.get("tracks") == 1

    # Media is indexed in place, not exploded to standalone S3 objects.
    assert s3.list_objects_v2(Bucket=output_bucket, Prefix=f"v1/{device}/").get("KeyCount", 0) == 0

    # Track row written to DynamoDB, stamped with the archive composite range.
    # The trigger keys tracks by "<track_id>_<timestamp>".
    track = tracks_table.get_item(Key={"track_id": "12224_163315", "device_id": device}).get("Item")
    assert track is not None
    assert track["archive_key"] == archive_key
    assert track["composite_key"] == composite_key
    offset, size = int(track["composite_offset"]), int(track["composite_size"])
    assert tar[offset:offset + size] == composite_bytes

    # Classification row written, stamped with the crop image range.
    clfs = classifications_table.query(KeyConditionExpression=Key("device_id").eq(device))["Items"]
    assert len(clfs) == 1
    assert clfs[0]["image_key"] == crop_key
    assert clfs[0]["archive_key"] == archive_key
    img_offset, img_size = int(clfs[0]["image_offset"]), int(clfs[0]["image_size"])
    assert len(tar[img_offset:img_offset + img_size]) == img_size

    # Idempotency is recorded in DynamoDB: a re-delivery is skipped, not reprocessed.
    resp2 = trigger.lambda_handler(_event(output_bucket, archive_key, etag), None)
    assert json.loads(resp2["body"])["processed"][0].get("skipped_duplicate") == 1
