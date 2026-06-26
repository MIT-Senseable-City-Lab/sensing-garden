"""Presigned upload helpers for processed edge26 output."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from bugcam.usage_logger import log_usage

RESULTS_FILENAME = "results.json"
MANIFEST_FILENAME = "manifest.json"
UPLOADED_STATE_FILENAME = ".uploaded"
DETECTION_META_FILENAME = ".detection.json"
EXPECTED_TRACKS_FILENAME = ".expected_tracks"
COMPLETED_TRACKS_FILENAME = ".completed_tracks"
DONE_MARKER_FILENAME = ".done"
REQUEST_TIMEOUT_SECONDS = 30
UPLOAD_TIMEOUT_SECONDS = 300


class RateLimitError(Exception):
    """Raised when the API returns 429 Too Many Requests."""

    def __init__(self, retry_after: int | None = None, message: str = ""):
        self.retry_after = retry_after
        super().__init__(message or f"Rate limited{f', retry after {retry_after}s' if retry_after else ''}")


def _iter_upload_files(local_dir: Path) -> list[Path]:
    skip_names = {
        UPLOADED_STATE_FILENAME,
        DETECTION_META_FILENAME,
        EXPECTED_TRACKS_FILENAME,
        COMPLETED_TRACKS_FILENAME,
        DONE_MARKER_FILENAME,
    }
    files = [path for path in sorted(local_dir.rglob("*")) if path.is_file() and path.name not in skip_names]
    return [path for path in files if path.name != RESULTS_FILENAME] + [path for path in files if path.name == RESULTS_FILENAME]


def get_upload_url(api_url: str, api_key: str, s3_key: str) -> str:
    t0 = time.monotonic()
    response = requests.post(
        f"{api_url.rstrip('/')}/upload-url",
        json={"s3_key": s3_key},
        headers={"X-Api-Key": api_key},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    duration_ms = (time.monotonic() - t0) * 1000
    if response.status_code == 429:
        retry_after = None
        if "Retry-After" in response.headers:
            try:
                retry_after = int(response.headers["Retry-After"])
            except (ValueError, TypeError):
                pass
        raise RateLimitError(retry_after=retry_after)
    response.raise_for_status()
    payload = response.json()
    upload_url = payload.get("upload_url")
    if not isinstance(upload_url, str) or not upload_url:
        raise ValueError("upload_url missing from backend response")
    log_usage(
        operation="get_upload_url",
        endpoint=f"{api_url}/upload-url",
        bytes_sent=len(json.dumps({"s3_key": s3_key}).encode("utf-8")),
        success=True,
        s3_key=s3_key,
        duration_ms=duration_ms,
    )
    return upload_url


def upload_bytes(api_url: str, api_key: str, data: bytes, s3_key: str, content_type: str) -> None:
    upload_url = get_upload_url(api_url, api_key, s3_key)
    bytes_sent = len(data)
    t0 = time.monotonic()
    try:
        response = requests.put(
            upload_url,
            data=data,
            headers={"Content-Type": content_type},
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
        duration_ms = (time.monotonic() - t0) * 1000
        if response.status_code == 429:
            retry_after = None
            if "Retry-After" in response.headers:
                try:
                    retry_after = int(response.headers["Retry-After"])
                except (ValueError, TypeError):
                    pass
            raise RateLimitError(retry_after=retry_after)
        response.raise_for_status()
    except Exception:
        log_usage(
            operation="upload_bytes",
            endpoint=upload_url.split("?")[0],
            bytes_sent=bytes_sent,
            success=False,
            s3_key=s3_key,
        )
        raise
    log_usage(
        operation="upload_bytes",
        endpoint=upload_url.split("?")[0],
        bytes_sent=bytes_sent,
        success=True,
        s3_key=s3_key,
        duration_ms=duration_ms,
    )


def upload_file(api_url: str, api_key: str, local_path: Path, s3_key: str) -> None:
    """Upload one file through a presigned PUT URL."""
    upload_url = get_upload_url(api_url, api_key, s3_key)
    data = local_path.read_bytes()
    bytes_sent = len(data)
    t0 = time.monotonic()
    try:
        response = requests.put(upload_url, data=data, timeout=UPLOAD_TIMEOUT_SECONDS)
        duration_ms = (time.monotonic() - t0) * 1000
        if response.status_code == 429:
            retry_after = None
            if "Retry-After" in response.headers:
                try:
                    retry_after = int(response.headers["Retry-After"])
                except (ValueError, TypeError):
                    pass
            raise RateLimitError(retry_after=retry_after)
        response.raise_for_status()
    except Exception:
        log_usage(
            operation="upload_file",
            endpoint=upload_url.split("?")[0],
            bytes_sent=bytes_sent,
            success=False,
            s3_key=s3_key,
        )
        raise
    log_usage(
        operation="upload_file",
        endpoint=upload_url.split("?")[0],
        bytes_sent=bytes_sent,
        success=True,
        s3_key=s3_key,
        duration_ms=duration_ms,
    )


def upload_directory(api_url: str, api_key: str, local_dir: Path, s3_prefix: str) -> None:
    """Upload all files in local_dir to s3_prefix, with results.json last."""
    for local_path in _iter_upload_files(local_dir):
        relative_path = local_path.relative_to(local_dir).as_posix()
        upload_file(api_url, api_key, local_path, f"{s3_prefix}/{relative_path}")


def upload_json(api_url: str, api_key: str, payload: Any, s3_key: str) -> None:
    serialized = json.dumps(payload, indent=2).encode("utf-8")
    upload_bytes(api_url, api_key, serialized, s3_key, "application/json")


def upload_manifest(api_url: str, api_key: str, flick_id: str, dot_ids: list[str]) -> None:
    """Upload manifest.json to the shared v1/ prefix."""
    upload_json(
        api_url,
        api_key,
        {"flick_id": flick_id, "dot_ids": dot_ids},
        f"v1/{MANIFEST_FILENAME}",
    )
