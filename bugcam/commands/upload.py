"""Upload processed output through backend-issued presigned URLs."""
from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from bugcam.config import (
    DEFAULT_API_URL,
    DEFAULT_S3_BUCKET,
    get_output_storage_dir,
    load_config,
    parse_dot_ids,
)
from bugcam.s3_upload import (
    RESULTS_FILENAME,
    UPLOADED_STATE_FILENAME,
    upload_directory,
    upload_file,
    upload_manifest,
)

app = typer.Typer(help="Upload processed output to S3", invoke_without_command=True, no_args_is_help=False)
console = Console()
HEARTBEAT_STATE_FILENAME = ".uploaded-heartbeats"
ENVIRONMENT_STATE_FILENAME = ".uploaded-environment"
LOG_STATE_FILENAME = ".uploaded-logs"
MAX_RETRY_DELAY_SECONDS = 300


def _list_result_directories(output_dir: Path) -> list[Path]:
    return sorted(results_path.parent for results_path in output_dir.rglob(RESULTS_FILENAME))


def _list_heartbeat_directories(output_dir: Path) -> list[Path]:
    return sorted(path for path in output_dir.glob("*/heartbeats") if path.is_dir())


def _list_environment_directories(output_dir: Path) -> list[Path]:
    return sorted(path for path in output_dir.glob("*/environment") if path.is_dir())


def _list_log_directories(output_dir: Path) -> list[Path]:
    return sorted(path for path in output_dir.glob("*/logs") if path.is_dir())


def _is_dot_results_dir(results_dir: Path, dot_ids: list[str]) -> bool:
    return results_dir.parent.name in dot_ids


def _uploaded_state_path(results_dir: Path) -> Path:
    return results_dir / UPLOADED_STATE_FILENAME


def _load_uploaded_state(results_dir: Path) -> dict[str, list[str]]:
    state_path = _uploaded_state_path(results_dir)
    if not state_path.exists():
        return {"track_ids": [], "files": []}
    return json.loads(state_path.read_text(encoding="utf-8"))


def _save_uploaded_state(results_dir: Path, state: dict[str, list[str]]) -> None:
    _uploaded_state_path(results_dir).write_text(json.dumps(state, indent=2), encoding="utf-8")


def _heartbeat_state_path(heartbeat_dir: Path) -> Path:
    return heartbeat_dir / HEARTBEAT_STATE_FILENAME


def _environment_state_path(environment_dir: Path) -> Path:
    return environment_dir / ENVIRONMENT_STATE_FILENAME


def _log_state_path(log_dir: Path) -> Path:
    return log_dir / LOG_STATE_FILENAME


def _heartbeat_fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _load_heartbeat_state(heartbeat_dir: Path) -> dict[str, str]:
    state_path = _heartbeat_state_path(heartbeat_dir)
    if not state_path.exists():
        return {}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError(f"Heartbeat upload state must be a JSON object: {state_path}")
    return {str(name): str(fingerprint) for name, fingerprint in state.items()}


def _save_heartbeat_state(heartbeat_dir: Path, uploaded_files: dict[str, str]) -> None:
    _heartbeat_state_path(heartbeat_dir).write_text(json.dumps(uploaded_files, indent=2), encoding="utf-8")


def _load_environment_state(environment_dir: Path) -> dict[str, str]:
    state_path = _environment_state_path(environment_dir)
    if not state_path.exists():
        return {}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError(f"Environment upload state must be a JSON object: {state_path}")
    return {str(name): str(fingerprint) for name, fingerprint in state.items()}


def _save_environment_state(environment_dir: Path, uploaded_files: dict[str, str]) -> None:
    _environment_state_path(environment_dir).write_text(json.dumps(uploaded_files, indent=2), encoding="utf-8")


def _load_log_state(log_dir: Path) -> dict[str, str]:
    state_path = _log_state_path(log_dir)
    if not state_path.exists():
        return {}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError(f"Log upload state must be a JSON object: {state_path}")
    return {str(name): str(fingerprint) for name, fingerprint in state.items()}


def _save_log_state(log_dir: Path, uploaded_files: dict[str, str]) -> None:
    _log_state_path(log_dir).write_text(json.dumps(uploaded_files, indent=2), encoding="utf-8")


def _load_result_track_ids(results_dir: Path) -> list[str]:
    payload = json.loads((results_dir / RESULTS_FILENAME).read_text(encoding="utf-8"))
    return [track["track_id"] for track in payload.get("tracks", [])]


def _upload_relative_file(results_dir: Path, api_url: str, api_key: str, s3_prefix: str, relative_path: Path) -> None:
    upload_file(api_url, api_key, results_dir / relative_path, f"{s3_prefix}/{relative_path.as_posix()}")


def _upload_heartbeat_files(output_dir: Path, api_url: str, api_key: str) -> int:
    uploaded_count = 0
    for heartbeat_dir in _list_heartbeat_directories(output_dir):
        device_id = heartbeat_dir.parent.name
        uploaded_files = _load_heartbeat_state(heartbeat_dir)
        changed = False
        for heartbeat_path in sorted(heartbeat_dir.glob("*.json")):
            fingerprint = _heartbeat_fingerprint(heartbeat_path)
            if uploaded_files.get(heartbeat_path.name) == fingerprint:
                continue
            upload_file(
                api_url,
                api_key,
                heartbeat_path,
                f"v1/{device_id}/heartbeats/{heartbeat_path.name}",
            )
            uploaded_files[heartbeat_path.name] = fingerprint
            changed = True
            uploaded_count += 1
        if changed:
            _save_heartbeat_state(heartbeat_dir, dict(sorted(uploaded_files.items())))
    return uploaded_count


def _upload_environment_files(output_dir: Path, api_url: str, api_key: str) -> int:
    uploaded_count = 0
    for environment_dir in _list_environment_directories(output_dir):
        device_id = environment_dir.parent.name
        uploaded_files = _load_environment_state(environment_dir)
        changed = False
        for environment_path in sorted(environment_dir.glob("*.json")):
            fingerprint = _heartbeat_fingerprint(environment_path)
            if uploaded_files.get(environment_path.name) == fingerprint:
                continue
            upload_file(
                api_url,
                api_key,
                environment_path,
                f"v1/{device_id}/environment/{environment_path.name}",
            )
            uploaded_files[environment_path.name] = fingerprint
            changed = True
            uploaded_count += 1
        if changed:
            _save_environment_state(environment_dir, dict(sorted(uploaded_files.items())))
    return uploaded_count


def _upload_log_files(output_dir: Path, api_url: str, api_key: str) -> int:
    uploaded_count = 0
    for log_dir in _list_log_directories(output_dir):
        device_id = log_dir.parent.name
        uploaded_files = _load_log_state(log_dir)
        changed = False
        for log_path in sorted(path for path in log_dir.iterdir() if path.is_file() and path.name != LOG_STATE_FILENAME):
            fingerprint = _heartbeat_fingerprint(log_path)
            if uploaded_files.get(log_path.name) == fingerprint:
                continue
            upload_file(
                api_url,
                api_key,
                log_path,
                f"v1/{device_id}/logs/{log_path.name}",
            )
            uploaded_files[log_path.name] = fingerprint
            changed = True
            uploaded_count += 1
        if changed:
            _save_log_state(log_dir, dict(sorted(uploaded_files.items())))
    return uploaded_count


def _upload_new_dot_files(
    results_dir: Path,
    api_url: str,
    api_key: str,
    s3_prefix: str,
    state: dict[str, list[str]],
) -> dict[str, list[str]]:
    uploaded_files = set(state["files"])
    track_ids = set(state["track_ids"])
    current_track_ids = _load_result_track_ids(results_dir)
    new_track_ids = [track_id for track_id in current_track_ids if track_id not in track_ids]

    for relative_path in sorted(
        path.relative_to(results_dir)
        for path in results_dir.rglob("*")
        if path.is_file() and path.name not in {RESULTS_FILENAME, UPLOADED_STATE_FILENAME}
    ):
        relative_key = relative_path.as_posix()
        if relative_key in uploaded_files:
            continue
        if relative_path.parts[0] == "videos":
            _upload_relative_file(results_dir, api_url, api_key, s3_prefix, relative_path)
            uploaded_files.add(relative_key)

    for track_id in new_track_ids:
        for crop_dir in sorted((results_dir / "crops").glob(f"{track_id}_*")):
            upload_directory(api_url, api_key, crop_dir, f"{s3_prefix}/crops/{crop_dir.name}")
            uploaded_files.add((Path("crops") / crop_dir.name).as_posix())
        for composite_path in sorted((results_dir / "composites").glob(f"{track_id}_*")):
            relative_path = Path("composites") / composite_path.name
            _upload_relative_file(results_dir, api_url, api_key, s3_prefix, relative_path)
            uploaded_files.add(relative_path.as_posix())
        label_path = results_dir / "labels" / f"{track_id}.json"
        if label_path.exists():
            relative_path = Path("labels") / label_path.name
            _upload_relative_file(results_dir, api_url, api_key, s3_prefix, relative_path)
            uploaded_files.add(relative_path.as_posix())
        track_ids.add(track_id)

    _upload_relative_file(results_dir, api_url, api_key, s3_prefix, Path(RESULTS_FILENAME))
    return {
        "track_ids": sorted(track_ids),
        "files": sorted(uploaded_files),
    }


def upload_ready_results(
    output_dir: Path,
    api_url: str,
    api_key: str,
    flick_id: str,
    dot_ids: list[str],
    delete_after_upload: bool,
    manifest_uploaded: bool,
) -> tuple[int, bool]:
    """Upload all ready result directories once."""
    processed_count = _upload_heartbeat_files(output_dir, api_url, api_key)
    processed_count += _upload_environment_files(output_dir, api_url, api_key)
    processed_count += _upload_log_files(output_dir, api_url, api_key)
    if not manifest_uploaded and _list_result_directories(output_dir):
        upload_manifest(api_url, api_key, flick_id, dot_ids)
        manifest_uploaded = True

    for results_dir in _list_result_directories(output_dir):
        s3_prefix = f"v1/{results_dir.parent.name}/{results_dir.name}"
        if _is_dot_results_dir(results_dir, dot_ids):
            state = _load_uploaded_state(results_dir)
            new_state = _upload_new_dot_files(results_dir, api_url, api_key, s3_prefix, state)
            if new_state != state:
                _save_uploaded_state(results_dir, new_state)
                processed_count += 1
            continue

        upload_directory(api_url, api_key, results_dir, s3_prefix)
        processed_count += 1
        if delete_after_upload:
            shutil.rmtree(results_dir)

    return processed_count, manifest_uploaded


def watch_uploads(
    output_dir: Path,
    api_url: str,
    api_key: str,
    flick_id: str,
    dot_ids: list[str],
    poll_interval: int,
    delete_after_upload: bool,
    stop_event: threading.Event,
) -> None:
    """Poll an output directory and upload ready results."""
    manifest_uploaded = False
    consecutive_failures = 0
    while not stop_event.is_set():
        try:
            _, manifest_uploaded = upload_ready_results(
                output_dir,
                api_url,
                api_key,
                flick_id,
                dot_ids,
                delete_after_upload,
                manifest_uploaded,
            )
            consecutive_failures = 0
            stop_event.wait(poll_interval)
        except Exception as exc:
            consecutive_failures += 1
            retry_delay = min(poll_interval * (2 ** consecutive_failures), MAX_RETRY_DELAY_SECONDS)
            console.print(f"[red]Upload failed[/red] {exc}. Retrying in {retry_delay}s.")
            stop_event.wait(retry_delay)


def _resolve_runtime_settings(
    api_url: str | None,
    api_key: str | None,
    flick_id: str | None,
    dot_ids: str | None,
    bucket: str | None,
) -> dict[str, Any]:
    config = load_config()
    resolved_api_url = api_url or str(config.get("api_url") or DEFAULT_API_URL)
    resolved_api_key = api_key or str(config.get("api_key") or "")
    resolved_flick_id = flick_id or str(config.get("flick_id") or config.get("device_id") or "")
    resolved_dot_ids = parse_dot_ids(dot_ids) if dot_ids is not None else parse_dot_ids(config.get("dot_ids"))
    resolved_bucket = bucket or str(config.get("s3_bucket") or DEFAULT_S3_BUCKET)

    missing_fields = [
        field_name
        for field_name, value in (
            ("api_key", resolved_api_key),
            ("flick_id", resolved_flick_id),
            ("s3_bucket", resolved_bucket),
        )
        if not value
    ]
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise typer.BadParameter(f"Missing required config values: {joined}. Run `bugcam setup` or pass CLI flags.")

    return {
        "api_url": resolved_api_url.rstrip("/"),
        "api_key": resolved_api_key,
        "flick_id": resolved_flick_id,
        "dot_ids": resolved_dot_ids,
        "s3_bucket": resolved_bucket,
    }


@app.callback()
def upload(
    output_dir: Path = typer.Option(get_output_storage_dir(), "--output-dir", help="Processed output directory to watch"),
    api_url: str | None = typer.Option(None, "--api-url", help="Backend API URL"),
    api_key: str | None = typer.Option(None, "--api-key", help="Per-device API key"),
    bucket: str | None = typer.Option(None, "--bucket", help="Configured output bucket"),
    poll_interval: int = typer.Option(30, "--poll-interval", help="Seconds between upload polls"),
    delete_after_upload: bool = typer.Option(
        True,
        "--delete-after-upload/--no-delete-after-upload",
        help="Clean up results after uploading",
    ),
    flick_id: str | None = typer.Option(None, "--flick-id", help="FLICK device ID"),
    dot_ids: str | None = typer.Option(None, "--dot-ids", help="Comma-separated DOT IDs"),
) -> None:
    """Watch an output directory and upload ready result directories."""
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = _resolve_runtime_settings(api_url, api_key, flick_id, dot_ids, bucket)
    stop_event = threading.Event()
    try:
        watch_uploads(
            output_dir,
            settings["api_url"],
            settings["api_key"],
            settings["flick_id"],
            settings["dot_ids"],
            poll_interval,
            delete_after_upload,
            stop_event,
        )
    except KeyboardInterrupt:
        stop_event.set()
        console.print("[yellow]Upload loop stopped[/yellow]")
