"""Heartbeat upload command."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from bugcam.config import DEFAULT_API_URL, DEFAULT_S3_BUCKET, get_input_storage_dir, load_config, parse_dot_ids
from bugcam.s3_upload import upload_json

app = typer.Typer(help="Upload a heartbeat snapshot", invoke_without_command=True, no_args_is_help=False)
console = Console()


def _read_cpu_temperature_celsius() -> float:
    raw_value = Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="utf-8").strip()
    return int(raw_value) / 1000.0


def _read_uptime_seconds() -> float:
    raw_value = Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
    return float(raw_value)


def _build_dot_status(input_dir: Path, dot_ids: list[str]) -> list[dict[str, str | None]]:
    status = []
    for dot_id in dot_ids:
        dot_dirs = sorted(path for path in input_dir.iterdir() if path.is_dir() and path.name.startswith(f"{dot_id}_"))
        latest_dir = dot_dirs[-1] if dot_dirs else None
        status.append(
            {
                "dot_id": dot_id,
                "last_modified": datetime.fromtimestamp(latest_dir.stat().st_mtime, tz=timezone.utc).isoformat() if latest_dir else None,
            }
        )
    return status


def build_heartbeat_payload(device_id: str, input_dir: Path, dot_ids: list[str]) -> dict[str, object]:
    """Build the heartbeat payload."""
    disk_usage = shutil.disk_usage(input_dir)
    return {
        "device_id": device_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cpu_temperature_celsius": _read_cpu_temperature_celsius(),
        "storage_free_bytes": disk_usage.free,
        "storage_total_bytes": disk_usage.total,
        "uptime_seconds": _read_uptime_seconds(),
        "dot_status": _build_dot_status(input_dir, dot_ids),
    }


def upload_heartbeat(api_url: str, api_key: str, device_id: str, input_dir: Path, dot_ids: list[str]) -> str:
    """Upload a heartbeat JSON document through a presigned URL."""
    payload = build_heartbeat_payload(device_id, input_dir, dot_ids)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    s3_key = f"v1/heartbeats/{device_id}/{timestamp}.json"
    upload_json(api_url, api_key, payload, s3_key)
    return s3_key


def _resolve_runtime_settings(
    api_url: str | None,
    api_key: str | None,
    device_id: str | None,
    dot_ids: str | None,
    bucket: str | None,
) -> dict[str, Any]:
    config = load_config()
    resolved_api_url = api_url or str(config.get("api_url") or DEFAULT_API_URL)
    resolved_api_key = api_key or str(config.get("api_key") or "")
    resolved_device_id = device_id or str(config.get("device_id") or "")
    resolved_dot_ids = parse_dot_ids(dot_ids) if dot_ids is not None else parse_dot_ids(config.get("dot_ids"))
    resolved_bucket = bucket or str(config.get("s3_bucket") or DEFAULT_S3_BUCKET)

    missing_fields = [
        field_name
        for field_name, value in (
            ("api_key", resolved_api_key),
            ("device_id", resolved_device_id),
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
        "dot_ids": resolved_dot_ids,
    }


@app.callback()
def heartbeat(
    api_url: str | None = typer.Option(None, "--api-url", help="Backend API URL"),
    api_key: str | None = typer.Option(None, "--api-key", help="Per-device API key"),
    device_id: str | None = typer.Option(None, "--device-id", help="Registered device ID"),
    dot_ids: str | None = typer.Option(None, "--dot-ids", help="Comma-separated DOT IDs"),
    bucket: str | None = typer.Option(None, "--bucket", help="Configured output bucket"),
    input_dir: Path = typer.Option(get_input_storage_dir(), "--input-dir", help="Directory containing DOT inputs"),
) -> None:
    """Upload a single heartbeat snapshot."""
    settings = _resolve_runtime_settings(api_url, api_key, device_id, dot_ids, bucket)
    s3_key = upload_heartbeat(
        api_url=settings["api_url"],
        api_key=settings["api_key"],
        device_id=settings["device_id"],
        input_dir=input_dir,
        dot_ids=settings["dot_ids"],
    )
    console.print(f"[green]Uploaded[/green] {s3_key}")
