"""All-in-one record, process, upload, and heartbeat command."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from bugcam.commands.heartbeat import write_heartbeat_snapshot
from bugcam.commands.upload import upload_ready_results, watch_uploads
from bugcam.app_config import apply_overrides, load_app_config
from bugcam.config import (
    DEFAULT_API_URL,
    DEFAULT_S3_BUCKET,
    get_default_flick_id,
    get_input_storage_dir,
    get_output_storage_dir,
    get_state_dir,
    parse_dot_ids,
)
from bugcam.commands.status import _check_time_sync
from bugcam.environment_sensor import collect_environment_reading
from bugcam.processing import load_detection_overrides, parse_capture_resolution
from bugcam.runtime import build_pipeline, resolve_bundle_provenance, select_model_reference
from bugcam.receiver import create_app
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


def _path_or_none(value: Any) -> Path | None:
    return Path(str(value)) if value else None


def _resolve_runtime_settings(app_config: dict[str, Any]) -> dict[str, Any]:
    device = app_config.get("device", {})
    resolved_api_url = str(device.get("api_url") or DEFAULT_API_URL)
    resolved_api_key = str(device.get("api_key") or "")
    resolved_flick_id = str(device.get("flick_id") or get_default_flick_id())
    resolved_dot_ids = parse_dot_ids(device.get("dot_ids"))
    resolved_bucket = str(device.get("s3_bucket") or DEFAULT_S3_BUCKET)

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
    settings_path: Path | None = typer.Option(None, "--settings", help="Path to a bugcam settings YAML (overrides bundled defaults)"),
    api_url: str | None = typer.Option(None, "--api-url", help="Backend API URL"),
    api_key: str | None = typer.Option(None, "--api-key", help="Per-device API key"),
    flick_id: str | None = typer.Option(None, "--flick-id", help="FLICK device ID"),
    dot_ids: str | None = typer.Option(None, "--dot-ids", help="Comma-separated DOT IDs"),
    input_dir: Path | None = typer.Option(None, "--input-dir", help="Directory for recorded input"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="Directory for processed output"),
    model: str | None = typer.Option(None, "--model", help="Model bundle name or model.hef path"),
    mode: str | None = typer.Option(None, "--mode", help="'continuous' (always recording) or 'interval' (record periodically)"),
    interval: int | None = typer.Option(None, "--interval", help="Minutes between recordings in interval mode"),
    chunk_duration: int | None = typer.Option(None, "--chunk-duration", help="Length of each recorded chunk in seconds"),
    fps: int | None = typer.Option(None, "--fps", help="Recording frame rate"),
    resolution: str | None = typer.Option(None, "--resolution", help="Recording resolution in WxH format"),
    bitrate: int | None = typer.Option(None, "--bitrate", help="H.264 encoder bitrate in bps (hardware encoding only)"),
    bucket: str | None = typer.Option(None, "--bucket", help="Configured output bucket"),
    upload_poll: int | None = typer.Option(None, "--upload-poll", help="Seconds between upload polls"),
    delete_after_upload: bool | None = typer.Option(
        None,
        "--delete-after-upload/--no-delete-after-upload",
        help="Clean up results after uploading",
    ),
    with_receiver: bool | None = typer.Option(
        None,
        "--with-receiver/--no-receiver",
        help="Start DOT receiver server alongside pipeline",
    ),
    receiver_port: int | None = typer.Option(None, "--receiver-port", help="DOT receiver HTTP port"),
    receiver_host: str | None = typer.Option(None, "--receiver-host", help="DOT receiver bind address"),
    detection_config: Path | None = typer.Option(None, "--detection-config", help="Path to a detection-only config YAML (merged into detection/tracking)"),
    detection_in_subprocess: bool | None = typer.Option(
        None,
        "--detection-in-subprocess/--detection-in-thread",
        help="Run detection in a separate process (own GIL) so it can't starve the recorder threads (default: on)",
    ),
) -> None:
    """Run recording, processing, uploading, and one-minute heartbeat emission."""
    if mode is not None and mode not in {"continuous", "interval"}:
        raise typer.BadParameter("mode must be 'continuous' or 'interval'")
    try:
        pid_path = _acquire_pid_file()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    try:
        ntp_ok, ntp_detail = _check_time_sync()
        if not ntp_ok:
            console.print(f"[yellow]Warning[/yellow] {ntp_detail}")

        parsed_resolution = _parse_resolution_option(resolution) if resolution else None
        parsed_dot_ids = parse_dot_ids(dot_ids) if dot_ids is not None else None

        app_config = load_app_config(settings_path)
        if detection_config is not None:
            det_over, trk_over = load_detection_overrides(detection_config)
            apply_overrides(app_config, "detection", **det_over)
            apply_overrides(app_config, "tracking", **trk_over)
        apply_overrides(app_config, "capture", fps=fps, bitrate=bitrate, chunk_duration_seconds=chunk_duration, resolution=parsed_resolution)
        apply_overrides(app_config, "pipeline", recording_mode=mode, recording_interval_minutes=interval, detection_in_subprocess=detection_in_subprocess)
        apply_overrides(app_config, "upload", poll_seconds=upload_poll, delete_after_upload=delete_after_upload)
        apply_overrides(app_config, "receiver", enabled=with_receiver, host=receiver_host, port=receiver_port)
        apply_overrides(app_config, "device", api_url=api_url, api_key=api_key, flick_id=flick_id, dot_ids=parsed_dot_ids, s3_bucket=bucket)

        if app_config["pipeline"]["recording_mode"] not in {"continuous", "interval"}:
            raise typer.BadParameter("mode must be 'continuous' or 'interval'")

        upload_poll = app_config["upload"]["poll_seconds"]
        delete_after_upload = app_config["upload"]["delete_after_upload"]
        with_receiver = app_config["receiver"]["enabled"]
        receiver_host = app_config["receiver"]["host"]
        receiver_port = app_config["receiver"]["port"]

        settings_paths = app_config.get("paths", {})
        input_dir = input_dir or _path_or_none(settings_paths.get("input_dir")) or get_input_storage_dir()
        output_dir = output_dir or _path_or_none(settings_paths.get("output_dir")) or get_output_storage_dir()

        settings = _resolve_runtime_settings(app_config)
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        selected_model = select_model_reference(model)
        provenance = resolve_bundle_provenance(selected_model)
        if model is None:
            console.print(f"[dim]Using model[/dim] {provenance['model_id']}")
        console.print(f"[cyan]Running[/cyan] flick={settings['flick_id']} dots={settings['dot_ids'] or '[]'}")
        console.print(f"[dim]Model[/dim] {provenance['model_id']}")

        pipeline = build_pipeline(
            app_config,
            flick_id=settings["flick_id"],
            dot_ids=settings["dot_ids"],
            input_dir=input_dir,
            output_dir=output_dir,
            model_reference=selected_model,
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
