"""Process existing media with the vendored edge26 pipeline."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from bugcam.app_config import apply_overrides, load_app_config
from bugcam.config import (
    get_default_flick_id,
    get_input_storage_dir,
    get_output_storage_dir,
    parse_dot_ids,
)
from bugcam.processing import load_detection_overrides
from bugcam.runtime import build_pipeline, resolve_bundle_provenance

app = typer.Typer(help="Process existing files with edge26", invoke_without_command=True, no_args_is_help=False)
console = Console()


def _as_path(value: Any) -> Path | None:
    return Path(str(value)) if value else None


@app.callback()
def process(
    settings_path: Path | None = typer.Option(None, "--settings", help="Path to a bugcam settings YAML (overrides bundled defaults)"),
    input_dir: Path | None = typer.Option(None, "--input-dir", help="Directory containing input videos and DOT folders"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="Directory for processed output"),
    model: str = typer.Option(..., "--model", help="Model bundle name or model.hef path"),
    flick_id: str | None = typer.Option(None, "--flick-id", help="FLICK device ID"),
    classification: bool | None = typer.Option(None, "--classification/--no-classification", help="Enable classification"),
    continuous_tracking: bool | None = typer.Option(None, "--continuous-tracking/--no-continuous-tracking", help="Track insects across FLICK chunks"),
    detection_config: Path | None = typer.Option(None, "--detection-config", help="Path to a detection-only config YAML (merged into detection/tracking)"),
) -> None:
    """Process existing files without recording."""
    app_config = load_app_config(settings_path)
    if detection_config is not None:
        det_over, trk_over = load_detection_overrides(detection_config)
        apply_overrides(app_config, "detection", **det_over)
        apply_overrides(app_config, "tracking", **trk_over)

    # Processing never records; processing is always on.
    apply_overrides(
        app_config,
        "pipeline",
        enable_recording=False,
        enable_processing=True,
        enable_classification=classification,
        continuous_tracking=continuous_tracking,
    )
    apply_overrides(app_config, "device", flick_id=flick_id)

    device = app_config.get("device", {})
    settings_paths = app_config.get("paths", {})
    resolved_flick_id = str(device.get("flick_id") or get_default_flick_id())
    dot_ids = parse_dot_ids(device.get("dot_ids"))
    input_dir = input_dir or _as_path(settings_paths.get("input_dir")) or get_input_storage_dir()
    output_dir = output_dir or _as_path(settings_paths.get("output_dir")) or get_output_storage_dir()
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    provenance = resolve_bundle_provenance(model)
    console.print(f"[cyan]Processing[/cyan] {input_dir} -> {output_dir}")
    console.print(f"[dim]Model[/dim] {provenance['model_id']} {provenance['model_sha256'][:12]}")
    pipeline = build_pipeline(
        app_config,
        flick_id=resolved_flick_id,
        dot_ids=dot_ids or [],
        input_dir=input_dir,
        output_dir=output_dir,
        model_reference=model,
    )
    pipeline.start()
    pipeline.wait()
