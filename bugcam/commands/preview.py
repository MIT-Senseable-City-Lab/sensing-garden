import typer
import subprocess
import sys
import os
from pathlib import Path
from rich.console import Console

app = typer.Typer(help="Camera preview and testing")
console = Console()

@app.callback(invoke_without_command=True)
def preview(
    duration: int = typer.Option(None, "--duration", "-d", help="Preview duration in seconds"),
    hef_path: str = typer.Option(None, "--model", "-m", help="Path to .hef model file"),
) -> None:
    """
    Start camera preview with optional detection overlay.

    If no model specified, shows raw camera feed.
    Press Ctrl+C to stop.
    """
    # Find the detection.py script
    detection_script = Path(__file__).parent.parent / "pipelines" / "detection.py"

    if not detection_script.exists():
        console.print(f"[red]Error: Detection script not found at {detection_script}[/red]")
        raise typer.Exit(1)

    # Find default model if none specified
    if hef_path is None:
        # Check cache directory first
        cache_dir = Path.home() / ".cache" / "bugcam" / "models"
        model_files = []

        if cache_dir.exists():
            model_files = list(cache_dir.glob("*.hef"))

        # Fall back to resources directory
        if not model_files:
            resources_dir = Path(__file__).parent.parent.parent / "resources"
            if resources_dir.exists():
                model_files = list(resources_dir.glob("*.hef"))

        if model_files:
            hef_path = str(model_files[0])
        else:
            console.print("[yellow]No model found[/yellow]")
            console.print("Download a model with: [cyan]bugcam models download[/cyan]")
            console.print("Running without detection overlay\n")

    # Build command - detection.py expects --input and --hef-path arguments
    cmd = [sys.executable, str(detection_script), "--input", "rpi"]

    if hef_path:
        cmd.extend(["--hef-path", hef_path])

    # Show startup message
    console.print("[green]Starting camera preview[/green]")
    if hef_path:
        console.print(f"Model: [cyan]{Path(hef_path).name}[/cyan]")
    console.print("Press [cyan]Ctrl+C[/cyan] to stop\n")

    process = None
    try:
        process = subprocess.Popen(cmd)
        process.wait()
        sys.exit(process.returncode)
    except KeyboardInterrupt:
        console.print("\n[green]Preview stopped[/green]")
        if process:
            process.terminate()
        sys.exit(0)
