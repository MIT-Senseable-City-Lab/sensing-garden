"""Collect one environmental reading from the bundled SEN55 reader."""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from bugcam.config import get_output_storage_dir
from bugcam.device_config import resolve_flick_id
from bugcam.environment_sensor import collect_environment_reading


app = typer.Typer(help="Collect one environmental reading", invoke_without_command=True, no_args_is_help=False)
console = Console()


@app.callback()
def environment(
    output_dir: Path | None = typer.Option(None, "--output-dir", help="Directory for processed output"),
    device_id: str | None = typer.Option(None, "--device-id", "--flick-id", help="FLICK device ID"),
) -> None:
    """Collect one environmental reading from the SEN55 sensor."""
    flick_id = resolve_flick_id(device_id)
    output_dir = output_dir or get_output_storage_dir()
    try:
        output_path, payload = collect_environment_reading(output_dir=output_dir, flick_id=flick_id)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Wrote[/green] {output_path}")
    console.print_json(json.dumps(payload))
