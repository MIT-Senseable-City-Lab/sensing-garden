"""All-in-one record, process, upload, and heartbeat command."""
from __future__ import annotations

import os
import threading
import time
import logging
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
    get_state_dir,
    load_config,
    parse_dot_ids,
)
from bugcam.commands.status import _check_time_sync
from bugcam.device_config import resolve_flick_id
from bugcam.environment_sensor import collect_environment_reading
from bugcam.processing import parse_capture_resolution
from bugcam.runtime import build_pipeline, resolve_bundle_provenance, select_model_reference
from bugcam.receiver import create_app
from bugcam.receiver.config import RECEIVER_DEFAULT_PORT, RECEIVER_DEFAULT_HOST
from bugcam.receiver.tracker import PendingTrackTracker

app = typer.Typer(help="Record, process, upload, and emit heartbeats", invoke_without_command=True, no_args_is_help=False)
console = Console()
HEARTBEAT_INTERVAL_SECONDS = 60
ENVIRONMENT_INTERVAL_SECONDS = 60
PID_FILE_PATH = get_state_dir() / "bugcam.pid"
logger = logging.getLogger(__name__)


def _heartbeat_loop(
    flick_id: str,
    input_dir: Path,
    output_dir: Path,
    dot_ids: list[str],
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        write_heartbeat_snapshot(output_dir, flick_id, input_dir, dot_ids)
        stop_event.wait(HEARTBEAT_INTERVAL_SECONDS)


def _environment_loop(
    flick_id: str,
    output_dir: Path,
    stop_event: threading.Event,
) -> None:
    warning_emitted = False
    while not stop_event.is_set():
        try:
            collect_environment_reading(output_dir=output_dir, flick_id=flick_id)
            warning_emitted = False
        except Exception as exc:
            if not warning_emitted:
                console.print(f"[yellow]Environment sensor warning[/yellow] {exc}")
                warning_emitted = True
        stop_event.wait(ENVIRONMENT_INTERVAL_SECONDS)


def _receiver_loop(
    host: str,
    port: int,
    stop_event: threading.Event,
) -> None:
    """Run the Flask receiver server in a thread."""
    flask_app = create_app(config={"host": host, "port": port})
    tracker = flask_app.config.get("TRACKER")

    if tracker:
        logger.info("Scanning for orphaned tracks...")
        tracker.recover_orphaned_tracks()

        finalization_stop = threading.Event()
        finalization_thread = threading.Thread(
            target=_finalization_loop,
            args=(tracker, finalization_stop),
            daemon=True
        )
        finalization_thread.start()
        logger.info("Track finalization thread started for receiver")

    logger.info(f"Receiver starting on {host}:{port}")
    flask_app.run(host=host, port=port, threaded=True, debug=False)

    if tracker and finalization_thread:
        finalization_stop.set()
        finalization_thread.join(timeout=5)


def _finalization_loop(tracker: PendingTrackTracker, stop_event: threading.Event):
    """Background thread that checks for idle tracks to finalize."""
    while not stop_event.is_set():
        try:
            tracker.check_pending()
        except Exception as e:
            logger.error(f"Finalization loop error: {e}")
        stop_event.wait(PendingTrackTracker.CHECK_INTERVAL)


def _parse_resolution_option(value: str) -> tuple[int, int]:
    try:
        return parse_capture_resolution(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


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
    resolved_flick_id = resolve_flick_id(flick_id)
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


def _process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_bugcam_process(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    return "bugcam" in result.stdout.lower()


def _acquire_pid_file() -> Path:
    PID_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if PID_FILE_PATH.exists():
        raw_pid = PID_FILE_PATH.read_text(encoding="utf-8").strip()
        if raw_pid.isdigit():
            pid = int(raw_pid)
            if _process_is_running(pid) and _is_bugcam_process(pid):
                raise RuntimeError(f"BugCam is already running (PID {raw_pid}). Use `kill {raw_pid}` to stop it first.")
        PID_FILE_PATH.unlink(missing_ok=True)

    PID_FILE_PATH.write_text(str(os.getpid()), encoding="utf-8")
    return PID_FILE_PATH


def _release_pid_file(pid_path: Path) -> None:
    if pid_path.exists():
        pid_path.unlink(missing_ok=True)


@app.callback()
def run(
    api_url: str | None = typer.Option(None, "--api-url", help="Backend API URL"),
    api_key: str | None = typer.Option(None, "--api-key", help="Per-device API key"),
    flick_id: str | None = typer.Option(None, "--flick-id", help="FLICK device ID"),
    dot_ids: str | None = typer.Option(None, "--dot-ids", help="Comma-separated DOT IDs"),
    input_dir: Path = typer.Option(get_input_storage_dir(), "--input-dir", help="Directory for recorded input"),
    output_dir: Path = typer.Option(get_output_storage_dir(), "--output-dir", help="Directory for processed output"),
    model: str | None = typer.Option(None, "--model", help="Model bundle name or model.hef path"),
    mode: str = typer.Option("continuous", "--mode", help="'continuous' (always recording) or 'interval' (record periodically)"),
    interval: int = typer.Option(5, "--interval", help="Minutes between recordings in interval mode"),
    chunk_duration: int = typer.Option(60, "--chunk-duration", help="Length of each recorded chunk in seconds"),
    resolution: str = typer.Option("1080x1080", "--resolution", help="Recording resolution in WxH format"),
    bucket: str | None = typer.Option(None, "--bucket", help="Configured output bucket"),
    upload_poll: int = typer.Option(30, "--upload-poll", help="Seconds between upload polls"),
    delete_after_upload: bool = typer.Option(
        True,
        "--delete-after-upload/--no-delete-after-upload",
        help="Clean up results after uploading",
    ),
    with_receiver: bool = typer.Option(
        True,
        "--with-receiver/--no-receiver",
        help="Start DOT receiver server alongside pipeline",
    ),
    receiver_port: int = typer.Option(RECEIVER_DEFAULT_PORT, "--receiver-port", help="DOT receiver HTTP port"),
    receiver_host: str = typer.Option(RECEIVER_DEFAULT_HOST, "--receiver-host", help="DOT receiver bind address"),
    detection_config: Path | None = typer.Option(None, "--detection-config", help="Path to detection config YAML file"),
) -> None:
    """Run recording, processing, uploading, and one-minute heartbeat emission."""
    if mode not in {"continuous", "interval"}:
        raise typer.BadParameter("mode must be 'continuous' or 'interval'")
    try:
        pid_path = _acquire_pid_file()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    parsed_resolution = _parse_resolution_option(resolution)

    try:
        ntp_ok, ntp_detail = _check_time_sync()
        if not ntp_ok:
            console.print(f"[yellow]Warning[/yellow] {ntp_detail}")

        settings = _resolve_runtime_settings(api_url, api_key, flick_id, dot_ids, bucket)
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        selected_model = select_model_reference(model)
        provenance = resolve_bundle_provenance(selected_model)
        if model is None:
            console.print(f"[dim]Using model[/dim] {provenance['model_id']}")
        console.print(f"[cyan]Running[/cyan] flick={settings['flick_id']} dots={settings['dot_ids'] or '[]'}")
        console.print(f"[dim]Model[/dim] {provenance['model_id']}")

        pipeline = build_pipeline(
            flick_id=settings["flick_id"],
            dot_ids=settings["dot_ids"],
            input_dir=input_dir,
            output_dir=output_dir,
            model_reference=selected_model,
            recording_mode=mode,
            recording_interval=interval,
            chunk_duration=chunk_duration,
            resolution=parsed_resolution,
            detection_config_path=detection_config,
        )
        upload_stop_event = threading.Event()
        heartbeat_stop_event = threading.Event()
        environment_stop_event = threading.Event()
        receiver_stop_event = threading.Event()
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
                settings["flick_id"],
                input_dir,
                output_dir,
                settings["dot_ids"],
                heartbeat_stop_event,
            ),
            daemon=True,
            name="BugCamHeartbeat",
        )
        environment_thread = threading.Thread(
            target=_environment_loop,
            args=(
                settings["flick_id"],
                output_dir,
                environment_stop_event,
            ),
            daemon=True,
            name="BugCamEnvironment",
        )

        receiver_thread = None
        if with_receiver:
            receiver_thread = threading.Thread(
                target=_receiver_loop,
                args=(receiver_host, receiver_port, receiver_stop_event),
                daemon=True,
                name="BugCamReceiver",
            )

        pipeline.start()
        upload_thread.start()
        heartbeat_thread.start()
        environment_thread.start()
        if receiver_thread:
            receiver_thread.start()
            console.print(f"[dim]Receiver[/dim] http://{receiver_host}:{receiver_port}")

        pipeline.wait()
    except KeyboardInterrupt:
        console.print("[yellow]Stopping recording and draining remaining work[/yellow]")
        pipeline.stop_recording()
        pipeline.wait()
    finally:
        if "upload_stop_event" in locals():
            upload_stop_event.set()
        if "heartbeat_stop_event" in locals():
            heartbeat_stop_event.set()
        if "environment_stop_event" in locals():
            environment_stop_event.set()
        if "receiver_stop_event" in locals() and receiver_thread:
            receiver_stop_event.set()
        if "upload_thread" in locals():
            upload_thread.join(timeout=upload_poll + 1)
        if "heartbeat_thread" in locals():
            heartbeat_thread.join(timeout=1)
        if "environment_thread" in locals():
            environment_thread.join(timeout=1)
        if "receiver_thread" in locals() and receiver_thread:
            receiver_thread.join(timeout=5)
        if "settings" in locals():
            upload_ready_results(
                output_dir,
                settings["api_url"],
                settings["api_key"],
                settings["flick_id"],
                settings["dot_ids"],
                delete_after_upload,
                False,
            )
        _release_pid_file(pid_path)
