"""Process existing media with the vendored edge26 pipeline."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from bugcam.config import get_input_storage_dir, get_output_storage_dir
from bugcam.device_config import load_device_config, resolve_flick_id
from bugcam.runtime import build_pipeline, resolve_bundle_provenance

app = typer.Typer(help="Process existing files with edge26", invoke_without_command=True, no_args_is_help=False)
console = Console()


@app.callback()
def process(
    input_dir: Path | None = typer.Option(None, "--input-dir", help="Directory containing input videos and DOT folders"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="Directory for processed output"),
    model: str = typer.Option(..., "--model", help="Model bundle name or model.hef path"),
    flick_id: str | None = typer.Option(None, "--flick-id", help="FLICK device ID"),
    classification: bool = typer.Option(True, "--classification/--no-classification", help="Enable classification"),
    continuous_tracking: bool = typer.Option(True, "--continuous-tracking/--no-continuous-tracking", help="Track insects across FLICK chunks"),
) -> None:
    """Process existing files without recording."""
    device_config = load_device_config()
    resolved_flick_id = resolve_flick_id(flick_id)
    input_dir = input_dir or get_input_storage_dir()
    output_dir = output_dir or get_output_storage_dir()
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = resolve_bundle_provenance(model)
    console.print(f"[cyan]Processing[/cyan] {input_dir} -> {output_dir}")
    console.print(f"[dim]Model[/dim] {provenance['model_id']} {provenance['model_sha256'][:12]}")
    pipeline = build_pipeline(
        flick_id=resolved_flick_id,
        dot_ids=device_config.dot_ids or [],
        input_dir=input_dir,
        output_dir=output_dir,
        model_reference=model,
        enable_recording=False,
        enable_processing=True,
        enable_classification=classification,
        continuous_tracking=continuous_tracking,
    )
    pipeline.start()
    pipeline.wait()
