"""All-in-one record, process, upload, and heartbeat command."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from bugcam.commands.heartbeat import write_heartbeat_snapshot
from bugcam.commands.upload import upload_ready_results, watch_uploads
from bugcam.config import (
    DEFAULT_API_URL,
    DEFAULT_S3_BUCKET,
    get_input_storage_dir,
    get_output_storage_dir,
    load_config,
    parse_dot_ids,
)
from bugcam.device_config import resolve_flick_id
from bugcam.processing import parse_capture_resolution
from bugcam.runtime import build_pipeline, resolve_bundle_provenance

app = typer.Typer(help="Record, process, upload, and emit heartbeats", invoke_without_command=True, no_args_is_help=False)
console = Console()
HEARTBEAT_INTERVAL_SECONDS = 3600


def _heartbeat_loop(
    device_id: str,
    input_dir: Path,
    output_dir: Path,
    dot_ids: list[str],
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        write_heartbeat_snapshot(output_dir, device_id, input_dir, dot_ids)
        stop_event.wait(HEARTBEAT_INTERVAL_SECONDS)


def _parse_resolution_option(value: str) -> tuple[int, int]:
    try:
        return parse_capture_resolution(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _resolve_runtime_settings(
    api_url: str | None,
    api_key: str | None,
    device_id: str | None,
    flick_id: str | None,
    dot_ids: str | None,
    bucket: str | None,
) -> dict[str, Any]:
    config = load_config()
    resolved_api_url = api_url or str(config.get("api_url") or DEFAULT_API_URL)
    resolved_api_key = api_key or str(config.get("api_key") or "")
    resolved_device_id = device_id or str(config.get("device_id") or "")
    resolved_flick_id = resolve_flick_id(flick_id)
    resolved_dot_ids = parse_dot_ids(dot_ids) if dot_ids is not None else parse_dot_ids(config.get("dot_ids"))
    resolved_bucket = bucket or str(config.get("s3_bucket") or DEFAULT_S3_BUCKET)

    missing_fields = [
        field_name
        for field_name, value in (
            ("api_key", resolved_api_key),
            ("device_id", resolved_device_id),
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
        "device_id": resolved_device_id,
        "flick_id": resolved_flick_id,
        "dot_ids": resolved_dot_ids,
        "s3_bucket": resolved_bucket,
    }


@app.callback()
def run(
    api_url: str | None = typer.Option(None, "--api-url", help="Backend API URL"),
    api_key: str | None = typer.Option(None, "--api-key", help="Per-device API key"),
    device_id: str | None = typer.Option(None, "--device-id", help="Registered device ID for heartbeats"),
    flick_id: str | None = typer.Option(None, "--flick-id", help="FLICK device ID"),
    dot_ids: str | None = typer.Option(None, "--dot-ids", help="Comma-separated DOT IDs"),
    input_dir: Path = typer.Option(get_input_storage_dir(), "--input-dir", help="Directory for recorded input"),
    output_dir: Path = typer.Option(get_output_storage_dir(), "--output-dir", help="Directory for processed output"),
    model: str = typer.Option(..., "--model", help="Model bundle name or model.hef path"),
    mode: str = typer.Option("continuous", "--mode", help="Recording mode: continuous or interval"),
    interval: int = typer.Option(5, "--interval", help="Minutes between recordings in interval mode"),
    chunk_duration: int = typer.Option(60, "--chunk-duration", help="Length of each recorded chunk in seconds"),
    resolution: str = typer.Option("1080x1080", "--resolution", help="Recording resolution in WxH format"),
    bucket: str | None = typer.Option(None, "--bucket", help="Configured output bucket"),
    upload_poll: int = typer.Option(30, "--upload-poll", help="Seconds between upload polls"),
    delete_after_upload: bool = typer.Option(False, "--delete-after-upload", help="Delete uploaded non-DOT result directories"),
) -> None:
    """Run recording, processing, uploading, and hourly heartbeat emission."""
    if mode not in {"continuous", "interval"}:
        raise typer.BadParameter("mode must be 'continuous' or 'interval'")
    parsed_resolution = _parse_resolution_option(resolution)

    settings = _resolve_runtime_settings(api_url, api_key, device_id, flick_id, dot_ids, bucket)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = resolve_bundle_provenance(model)
    console.print(f"[cyan]Running[/cyan] flick={settings['flick_id']} dots={settings['dot_ids'] or '[]'}")
    console.print(f"[dim]Model[/dim] {provenance['model_id']} {provenance['model_sha256'][:12]}")

    pipeline = build_pipeline(
        flick_id=settings["flick_id"],
        dot_ids=settings["dot_ids"],
        input_dir=input_dir,
        output_dir=output_dir,
        model_reference=model,
        recording_mode=mode,
        recording_interval=interval,
        chunk_duration=chunk_duration,
        resolution=parsed_resolution,
    )
    upload_stop_event = threading.Event()
    heartbeat_stop_event = threading.Event()
    upload_thread = threading.Thread(
        target=watch_uploads,
        args=(
            output_dir,
            settings["api_url"],
            settings["api_key"],
            settings["flick_id"],
            settings["dot_ids"],
            upload_poll,
            delete_after_upload,
            upload_stop_event,
        ),
        daemon=True,
        name="BugCamUpload",
    )
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(
            settings["device_id"],
            input_dir,
            output_dir,
            settings["dot_ids"],
            heartbeat_stop_event,
        ),
        daemon=True,
        name="BugCamHeartbeat",
    )

    pipeline.start()
    upload_thread.start()
    heartbeat_thread.start()

    try:
        pipeline.wait()
    except KeyboardInterrupt:
        console.print("[yellow]Stopping recording and draining remaining work[/yellow]")
        pipeline.stop_recording()
        pipeline.wait()
    finally:
        upload_stop_event.set()
        heartbeat_stop_event.set()
        upload_thread.join(timeout=upload_poll + 1)
        heartbeat_thread.join(timeout=1)
        upload_ready_results(
            output_dir,
            settings["api_url"],
            settings["api_key"],
            settings["flick_id"],
            settings["dot_ids"],
            delete_after_upload,
            False,
        )
