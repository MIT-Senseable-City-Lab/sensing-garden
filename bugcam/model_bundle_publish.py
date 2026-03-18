"""Helpers for publishing model bundles to S3 without touching legacy flat objects."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .model_bundles import BUNDLE_LABELS_FILENAME, BUNDLE_MODEL_FILENAME

DEFAULT_MODELS_BUCKET = "scl-sensing-garden-models"


@dataclass(frozen=True)
class BundleUploadObject:
    """One object that should exist in a remote model bundle."""

    local_path: Path
    key: str


def _normalize_prefix(prefix: str) -> str:
    prefix = prefix.strip().strip("/")
    return f"{prefix}/" if prefix else ""


def build_bundle_upload_objects(
    bundle_name: str,
    model_path: Path,
    labels_path: Path,
    prefix: str = "",
) -> list[BundleUploadObject]:
    """Return the exact S3 objects required for a bundle."""
    if not bundle_name or "/" in bundle_name.strip("/"):
        raise ValueError("bundle_name must be a single path segment")
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    if not labels_path.exists():
        raise FileNotFoundError(f"Labels file not found: {labels_path}")

    key_prefix = _normalize_prefix(prefix)
    bundle_root = f"{key_prefix}{bundle_name}"
    return [
        BundleUploadObject(local_path=model_path, key=f"{bundle_root}/{BUNDLE_MODEL_FILENAME}"),
        BundleUploadObject(local_path=labels_path, key=f"{bundle_root}/{BUNDLE_LABELS_FILENAME}"),
    ]


def object_exists(s3_client, bucket: str, key: str) -> bool:
    """Return True if the object already exists."""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:  # boto3/botocore exception typing is noisy here
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def publish_bundle(
    bundle_name: str,
    model_path: Path,
    labels_path: Path,
    *,
    bucket: str = DEFAULT_MODELS_BUCKET,
    prefix: str = "",
    overwrite: bool = False,
    verify: bool = True,
    dry_run: bool = False,
    s3_client=None,
) -> list[str]:
    """Upload a bundle to S3 and optionally verify it."""
    objects = build_bundle_upload_objects(
        bundle_name=bundle_name,
        model_path=model_path,
        labels_path=labels_path,
        prefix=prefix,
    )

    if dry_run:
        return [obj.key for obj in objects]

    if s3_client is None:
        import boto3

        client = boto3.client("s3")
    else:
        client = s3_client

    if not overwrite:
        existing = [obj.key for obj in objects if object_exists(client, bucket, obj.key)]
        if existing:
            joined = ", ".join(existing)
            raise FileExistsError(f"Refusing to overwrite existing bundle objects: {joined}")

    for obj in objects:
        client.upload_file(str(obj.local_path), bucket, obj.key)

    if verify:
        missing = [obj.key for obj in objects if not object_exists(client, bucket, obj.key)]
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Uploaded bundle verification failed for: {joined}")

    return [obj.key for obj in objects]


def format_bundle_publish_summary(bucket: str, keys: Iterable[str]) -> str:
    """Return a human-readable summary of uploaded keys."""
    key_list = list(keys)
    body = "\n".join(f"  - s3://{bucket}/{key}" for key in key_list)
    return f"Bundle objects:\n{body}"
