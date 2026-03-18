"""Filesystem-backed job queue for bugcam media workflows."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    get_default_device_id,
    get_incoming_dir,
    get_iphone_watch_dir,
    get_jobs_dir,
    get_outputs_dir,
    get_recordings_dir,
)
from .processing import get_processor_manager

JOB_DIR_NAMES = {
    "unprocessed": "unprocessed",
    "processing": "processing",
    "processed": "processed",
    "uploading": "upload",
    "failed": "failed",
    "completed": "completed",
}

RETRYABLE_STAGES = {"process", "upload"}
MEDIA_EXTENSIONS = {".avi", ".mkv", ".mov", ".mp4", ".webm"}


def now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def get_job_dirs() -> dict[str, Path]:
    """Return the managed job directories."""
    jobs_dir = get_jobs_dir()
    incoming_dir = get_incoming_dir()
    outputs_dir = get_outputs_dir()
    directories = {
        "jobs": jobs_dir,
        "incoming": incoming_dir,
        "incoming_unprocessed": incoming_dir / "unprocessed",
        "outputs": outputs_dir,
    }
    for stage, dirname in JOB_DIR_NAMES.items():
        directories[stage] = jobs_dir / dirname
    return directories


def ensure_job_dirs() -> dict[str, Path]:
    """Create all managed job directories."""
    directories = get_job_dirs()
    for path in directories.values():
        path.mkdir(parents=True, exist_ok=True)
    get_iphone_watch_dir().mkdir(parents=True, exist_ok=True)
    get_recordings_dir().mkdir(parents=True, exist_ok=True)
    return directories


def _manifest_path(stage: str, job_id: str) -> Path:
    return ensure_job_dirs()[stage] / f"{job_id}.json"


def _write_job(stage: str, job: dict[str, Any]) -> Path:
    path = _manifest_path(stage, job["job_id"])
    path.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _load_job(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _list_job_paths(stage: str) -> list[Path]:
    return sorted(_manifest_path(stage, "").parent.glob("*.json"))


def _all_job_paths() -> list[Path]:
    ensure_job_dirs()
    paths: list[Path] = []
    for stage in ("unprocessed", "processing", "processed", "uploading", "failed", "completed"):
        paths.extend(_list_job_paths(stage))
    return sorted(paths)


def build_fingerprint(path: Path) -> str:
    """Build a stable fingerprint for a watched source file."""
    stat = path.stat()
    raw = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _existing_fingerprints() -> set[str]:
    fingerprints = set()
    for path in _all_job_paths():
        try:
            job = _load_job(path)
            fingerprint = job.get("fingerprint")
            if fingerprint:
                fingerprints.add(fingerprint)
        except Exception:
            continue
    return fingerprints


def _existing_job_ids() -> set[str]:
    return {path.stem for path in _all_job_paths()}


def discover_source_files() -> list[tuple[str, Path]]:
    """List watched media files across all sources."""
    sources = [
        ("iphone", get_iphone_watch_dir()),
        ("rpi", get_recordings_dir()),
    ]
    discovered: list[tuple[str, Path]] = []
    for source_type, source_dir in sources:
        if not source_dir.exists():
            continue
        for path in sorted(source_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            discovered.append((source_type, path))
    return discovered


def create_job_from_source(source_type: str, source_path: Path) -> dict[str, Any] | None:
    """Copy a watched file into managed storage and register a job."""
    ensure_job_dirs()

    fingerprint = build_fingerprint(source_path)
    if fingerprint in _existing_fingerprints():
        return None

    job_id = uuid.uuid4().hex
    while job_id in _existing_job_ids():
        job_id = uuid.uuid4().hex

    managed_media_path = ensure_job_dirs()["incoming_unprocessed"] / f"{job_id}{source_path.suffix.lower()}"
    shutil.copy2(source_path, managed_media_path)

    guessed_type, _ = mimetypes.guess_type(source_path.name)
    created_at = now_iso()
    job = {
        "job_id": job_id,
        "stage": "unprocessed",
        "source_type": source_type,
        "logical_device_id": get_default_device_id(source_type),
        "continuity_key": get_default_device_id(source_type),
        "source_path": str(source_path),
        "managed_media_path": str(managed_media_path),
        "original_filename": source_path.name,
        "fingerprint": fingerprint,
        "content_type": guessed_type or "application/octet-stream",
        "created_at": created_at,
        "updated_at": created_at,
        "capture_timestamp": datetime.fromtimestamp(source_path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "attempts": {"process": 0, "upload": 0},
        "processing": {},
        "upload": {},
        "errors": [],
    }
    _write_job("unprocessed", job)
    return job


def transition_job(job: dict[str, Any], from_stage: str, to_stage: str) -> dict[str, Any]:
    """Move a job manifest between queue stages."""
    current_path = _manifest_path(from_stage, job["job_id"])
    if current_path.exists():
        current_path.unlink()
    job["stage"] = to_stage
    job["updated_at"] = now_iso()
    _write_job(to_stage, job)
    return job


def mark_job_failed(job: dict[str, Any], from_stage: str, failed_stage: str, error: Exception) -> dict[str, Any]:
    """Move a job to the failed directory and store the error."""
    job.setdefault("errors", []).append(
        {
            "stage": failed_stage,
            "message": str(error),
            "timestamp": now_iso(),
        }
    )
    job["failed_stage"] = failed_stage
    return transition_job(job, from_stage, "failed")


def run_ingest() -> dict[str, int]:
    """Scan watched folders and register new jobs."""
    ensure_job_dirs()
    discovered = 0
    created = 0
    skipped = 0
    for source_type, source_path in discover_source_files():
        discovered += 1
        job = create_job_from_source(source_type, source_path)
        if job is None:
            skipped += 1
        else:
            created += 1
    return {"discovered": discovered, "created": created, "skipped": skipped}


def _process_job(job: dict[str, Any]) -> dict[str, Any]:
    processor = get_processor_manager()
    media_path = Path(job["managed_media_path"])
    output_dir = ensure_job_dirs()["outputs"] / job["job_id"]
    result = processor.process(media_path, output_dir, job)
    job["processing"] = result
    job["output_dir"] = str(output_dir)
    return job


def run_process() -> dict[str, int]:
    """Process queued jobs."""
    ensure_job_dirs()
    processed = 0
    failed = 0

    for path in _list_job_paths("unprocessed"):
        job = _load_job(path)
        transition_job(job, "unprocessed", "processing")
        try:
            job["attempts"]["process"] += 1
            job = _process_job(job)
            transition_job(job, "processing", "processed")
            processed += 1
        except Exception as exc:
            mark_job_failed(job, "processing", "process", exc)
            failed += 1

    return {"processed": processed, "failed": failed}


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def upload_job(job: dict[str, Any]) -> dict[str, Any]:
    """Upload a processed job to the Sensing Garden backend."""
    from sensing_garden_client import SensingGardenClient

    api_key = _require_env("SENSING_GARDEN_API_KEY")
    base_url = _require_env("API_BASE_URL")
    aws_access_key_id = _require_env("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = _require_env("AWS_SECRET_ACCESS_KEY")
    device_id = os.environ.get("DEVICE_ID") or job.get("logical_device_id") or f"bugcam-{job['source_type']}"

    client = SensingGardenClient(
        base_url=base_url,
        api_key=api_key,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )

    metadata = {
        "job_id": job["job_id"],
        "source_type": job["source_type"],
        "logical_device_id": job.get("logical_device_id"),
        "original_filename": job["original_filename"],
        "processing": job.get("processing", {}),
    }

    response = client.videos.upload_video(
        device_id=device_id,
        timestamp=job["capture_timestamp"],
        video_path_or_data=job["managed_media_path"],
        content_type=job["content_type"],
        metadata=metadata,
    )
    job["upload"] = {"device_id": device_id, "response": response, "uploaded_at": now_iso()}
    return job


def run_upload() -> dict[str, int]:
    """Upload processed jobs."""
    ensure_job_dirs()
    uploaded = 0
    failed = 0

    for path in _list_job_paths("processed"):
        job = _load_job(path)
        transition_job(job, "processed", "uploading")
        try:
            job["attempts"]["upload"] += 1
            job = upload_job(job)
            transition_job(job, "uploading", "completed")
            uploaded += 1
        except Exception as exc:
            mark_job_failed(job, "uploading", "upload", exc)
            failed += 1

    return {"uploaded": uploaded, "failed": failed}


def get_job_counts() -> dict[str, int]:
    """Return counts for each queue stage."""
    ensure_job_dirs()
    return {
        "unprocessed": len(_list_job_paths("unprocessed")),
        "processing": len(_list_job_paths("processing")),
        "processed": len(_list_job_paths("processed")),
        "upload": len(_list_job_paths("uploading")),
        "failed": len(_list_job_paths("failed")),
        "completed": len(_list_job_paths("completed")),
    }


def retry_failed_jobs(stage: str | None = None, job_id: str | None = None) -> dict[str, int]:
    """Retry failed jobs back into the correct queue stage."""
    ensure_job_dirs()
    retried = 0
    skipped = 0

    for path in _list_job_paths("failed"):
        job = _load_job(path)
        failed_stage = job.get("failed_stage")
        if failed_stage not in RETRYABLE_STAGES:
            skipped += 1
            continue
        if stage and failed_stage != stage:
            skipped += 1
            continue
        if job_id and job["job_id"] != job_id:
            skipped += 1
            continue

        job.pop("failed_stage", None)
        if failed_stage == "process":
            transition_job(job, "failed", "unprocessed")
        elif failed_stage == "upload":
            transition_job(job, "failed", "processed")
        retried += 1

    return {"retried": retried, "skipped": skipped}
