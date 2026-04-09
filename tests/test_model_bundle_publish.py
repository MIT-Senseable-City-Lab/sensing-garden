"""Tests for safe S3 model bundle publishing."""
from pathlib import Path

import pytest

from bugcam.model_bundle_publish import (
    BUNDLE_LABELS_FILENAME,
    BUNDLE_MODEL_FILENAME,
    build_bundle_upload_objects,
    format_bundle_publish_summary,
    publish_bundle,
)


class FakeS3Client:
    def __init__(self, existing: set[str] | None = None):
        self.existing = set(existing or set())
        self.uploads: list[tuple[str, str, str]] = []

    def head_object(self, Bucket: str, Key: str):
        if Key in self.existing:
            return {"Bucket": Bucket, "Key": Key}
        error = Exception("Not found")
        error.response = {"Error": {"Code": "404"}}
        raise error

    def upload_file(self, Filename: str, Bucket: str, Key: str):
        self.uploads.append((Filename, Bucket, Key))
        self.existing.add(Key)


def test_build_bundle_upload_objects(tmp_path: Path) -> None:
    model_path = tmp_path / "model.hef"
    labels_path = tmp_path / "labels.txt"
    model_path.write_bytes(b"hef")
    labels_path.write_text("species-a\n", encoding="utf-8")

    objects = build_bundle_upload_objects(
        bundle_name="london_141-multitask",
        model_path=model_path,
        labels_path=labels_path,
    )

    assert [obj.key for obj in objects] == [
        f"london_141-multitask/{BUNDLE_MODEL_FILENAME}",
        f"london_141-multitask/{BUNDLE_LABELS_FILENAME}",
    ]


def test_build_bundle_upload_objects_with_prefix(tmp_path: Path) -> None:
    model_path = tmp_path / "model.hef"
    labels_path = tmp_path / "labels.txt"
    model_path.write_bytes(b"hef")
    labels_path.write_text("species-a\n", encoding="utf-8")

    objects = build_bundle_upload_objects(
        bundle_name="yolov8s",
        model_path=model_path,
        labels_path=labels_path,
        prefix="staging/models",
    )

    assert [obj.key for obj in objects] == [
        f"staging/models/yolov8s/{BUNDLE_MODEL_FILENAME}",
        f"staging/models/yolov8s/{BUNDLE_LABELS_FILENAME}",
    ]


def test_publish_bundle_dry_run_does_not_upload(tmp_path: Path) -> None:
    model_path = tmp_path / "model.hef"
    labels_path = tmp_path / "labels.txt"
    model_path.write_bytes(b"hef")
    labels_path.write_text("species-a\n", encoding="utf-8")
    client = FakeS3Client()

    keys = publish_bundle(
        bundle_name="yolov8s",
        model_path=model_path,
        labels_path=labels_path,
        dry_run=True,
        s3_client=client,
    )

    assert keys == [
        f"yolov8s/{BUNDLE_MODEL_FILENAME}",
        f"yolov8s/{BUNDLE_LABELS_FILENAME}",
    ]
    assert client.uploads == []


def test_publish_bundle_refuses_existing_objects(tmp_path: Path) -> None:
    model_path = tmp_path / "model.hef"
    labels_path = tmp_path / "labels.txt"
    model_path.write_bytes(b"hef")
    labels_path.write_text("species-a\n", encoding="utf-8")
    client = FakeS3Client(existing={f"yolov8s/{BUNDLE_MODEL_FILENAME}"})

    with pytest.raises(FileExistsError):
        publish_bundle(
            bundle_name="yolov8s",
            model_path=model_path,
            labels_path=labels_path,
            s3_client=client,
        )


def test_publish_bundle_uploads_and_verifies(tmp_path: Path) -> None:
    model_path = tmp_path / "model.hef"
    labels_path = tmp_path / "labels.txt"
    model_path.write_bytes(b"hef")
    labels_path.write_text("species-a\n", encoding="utf-8")
    client = FakeS3Client()

    keys = publish_bundle(
        bundle_name="yolov8s",
        model_path=model_path,
        labels_path=labels_path,
        s3_client=client,
    )

    assert keys == [
        f"yolov8s/{BUNDLE_MODEL_FILENAME}",
        f"yolov8s/{BUNDLE_LABELS_FILENAME}",
    ]
    assert len(client.uploads) == 2


def test_format_bundle_publish_summary() -> None:
    summary = format_bundle_publish_summary(
        "scl-sensing-garden-models",
        ["yolov8s/model.hef", "yolov8s/labels.txt"],
    )
    assert "s3://scl-sensing-garden-models/yolov8s/model.hef" in summary
    assert "s3://scl-sensing-garden-models/yolov8s/labels.txt" in summary
