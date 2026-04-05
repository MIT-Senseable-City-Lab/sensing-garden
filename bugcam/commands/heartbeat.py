"""Heartbeat snapshot command."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from bugcam.config import get_input_storage_dir, get_output_storage_dir, load_config, parse_dot_ids

app = typer.Typer(help="Write a heartbeat snapshot", invoke_without_command=True, no_args_is_help=False)
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


def build_heartbeat_payload(
    flick_id: str,
    input_dir: Path,
    dot_ids: list[str],
    *,
    timestamp: datetime | None = None,
) -> dict[str, object]:
    """Build the heartbeat payload."""
    heartbeat_time = timestamp or datetime.now(timezone.utc)
    disk_usage = shutil.disk_usage(input_dir)
    return {
        "device_id": flick_id,
        "timestamp": heartbeat_time.isoformat(),
        "cpu_temperature_celsius": _read_cpu_temperature_celsius(),
        "storage_free_bytes": disk_usage.free,
        "storage_total_bytes": disk_usage.total,
        "uptime_seconds": _read_uptime_seconds(),
        "dot_status": _build_dot_status(input_dir, dot_ids),
    }


def write_heartbeat_snapshot(output_dir: Path, flick_id: str, input_dir: Path, dot_ids: list[str]) -> Path:
    """Write a heartbeat JSON document to the output directory."""
    heartbeat_time = datetime.now(timezone.utc)
    payload = build_heartbeat_payload(flick_id, input_dir, dot_ids, timestamp=heartbeat_time)
    heartbeat_dir = output_dir / flick_id / "heartbeats"
    heartbeat_dir.mkdir(parents=True, exist_ok=True)
    heartbeat_path = heartbeat_dir / f"{heartbeat_time.strftime('%Y%m%d_%H%M%S')}.json"
    heartbeat_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return heartbeat_path


def _resolve_runtime_settings(
    flick_id: str | None,
    dot_ids: str | None,
) -> dict[str, Any]:
    config = load_config()
    resolved_flick_id = flick_id or str(config.get("flick_id") or config.get("device_id") or "")
    resolved_dot_ids = parse_dot_ids(dot_ids) if dot_ids is not None else parse_dot_ids(config.get("dot_ids"))

    missing_fields = [
        field_name
        for field_name, value in (
            ("flick_id", resolved_flick_id),
        )
        if not value
    ]
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise typer.BadParameter(f"Missing required config values: {joined}. Run `bugcam setup` or pass CLI flags.")

    return {
        "flick_id": resolved_flick_id,
        "dot_ids": resolved_dot_ids,
    }


@app.callback()
def heartbeat(
    flick_id: str | None = typer.Option(None, "--flick-id", help="FLICK device ID"),
    dot_ids: str | None = typer.Option(None, "--dot-ids", help="Comma-separated DOT IDs"),
    input_dir: Path = typer.Option(get_input_storage_dir(), "--input-dir", help="Directory containing DOT inputs"),
    output_dir: Path = typer.Option(get_output_storage_dir(), "--output-dir", help="Directory for processed output"),
) -> None:
    """Write a single heartbeat snapshot."""
    settings = _resolve_runtime_settings(flick_id, dot_ids)
    heartbeat_path = write_heartbeat_snapshot(
        output_dir=output_dir,
        flick_id=settings["flick_id"],
        input_dir=input_dir,
        dot_ids=settings["dot_ids"],
    )
    console.print(f"[green]Wrote[/green] {heartbeat_path}")
