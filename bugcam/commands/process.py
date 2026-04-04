"""Process existing media with the vendored edge26 pipeline."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from bugcam.config import get_default_dot_ids, get_default_flick_id, get_input_storage_dir, get_output_storage_dir
from bugcam.runtime import build_pipeline, resolve_bundle_provenance

app = typer.Typer(help="Process existing files with edge26", invoke_without_command=True, no_args_is_help=False)
console = Console()


@app.callback()
def process(
    input_dir: Path = typer.Option(get_input_storage_dir(), "--input-dir", help="Directory containing input videos and DOT folders"),
    output_dir: Path = typer.Option(get_output_storage_dir(), "--output-dir", help="Directory for processed output"),
    model: str = typer.Option(..., "--model", help="Model bundle name or model.hef path"),
    classification: bool = typer.Option(True, "--classification/--no-classification", help="Enable classification"),
    continuous_tracking: bool = typer.Option(True, "--continuous-tracking/--no-continuous-tracking", help="Track insects across FLICK chunks"),
) -> None:
    """Process existing files without recording."""
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = resolve_bundle_provenance(model)
    console.print(f"[cyan]Processing[/cyan] {input_dir} -> {output_dir}")
    console.print(f"[dim]Model[/dim] {provenance['model_id']} {provenance['model_sha256'][:12]}")
    pipeline = build_pipeline(
        flick_id=get_default_flick_id(),
        dot_ids=get_default_dot_ids(),
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
