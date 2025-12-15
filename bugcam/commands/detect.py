import typer
import subprocess
import sys
import json
import signal
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(help="Run insect detection")
console = Console()


def get_python_for_detection() -> str:
    """Get the Python interpreter to use for detection script.

    On Linux (Raspberry Pi), use system Python to access system packages
    like gi and hailo that can't be pip installed.
    """
    if platform.system() == "Linux" and Path("/usr/bin/python3").exists():
        return "/usr/bin/python3"
    return sys.executable


@app.command()
def start(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model name or path (default: auto-detect)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file for detections (JSONL format)"),
    duration: Optional[int] = typer.Option(None, "--duration", "-d", help="Run for N minutes then stop"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress live output"),
) -> None:
    """
    Start insect detection.

    Runs continuously until Ctrl+C or duration expires.
    Detections are printed to console and optionally saved to file.
    """
    # Find model path
    model_path = _resolve_model_path(model)
    if not model_path:
        _show_model_not_found_help()
        raise typer.Exit(1)

    # Find detection.py script
    detection_script = Path(__file__).parent.parent / "pipelines" / "detection.py"
    if not detection_script.exists():
        console.print(f"[red]Error: Detection script not found at {detection_script}[/red]")
        raise typer.Exit(1)

    # Validate duration
    if duration is not None and duration <= 0:
        console.print("[red]Error: Duration must be positive[/red]")
        raise typer.Exit(1)

    # Show startup banner
    if not quiet:
        _show_startup_banner(model_path, output, duration)

    # Build command - use system Python on Linux to access gi/hailo system packages
    cmd = [
        get_python_for_detection(),
        str(detection_script),
        "--input", "rpi",
        "--hef-path", str(model_path)
    ]

    # Setup output file if specified
    output_file = None
    detection_count = 0
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output_file = open(output, 'a')

    # Setup duration timer if specified
    start_time = datetime.now()
    if duration:
        signal.alarm(duration * 60)

    process = None
    try:
        if not quiet:
            console.print("[cyan]Detection running[/cyan] - Press Ctrl+C to stop\n")

        # Run detection process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # Stream output
        for line in process.stdout:
            if not quiet:
                print(line, end='')

            # Write to output file if specified
            if output_file:
                # Try to parse detection lines and convert to JSON
                if "Detection:" in line:
                    try:
                        detection_data = {
                            "timestamp": datetime.now().isoformat(),
                            "raw": line.strip()
                        }
                        output_file.write(json.dumps(detection_data) + '\n')
                        output_file.flush()
                        detection_count += 1
                    except Exception:
                        # If parsing fails, just write the raw line
                        pass

        process.wait()

    except KeyboardInterrupt:
        if not quiet:
            console.print("\n[yellow]Stopping detection...[/yellow]")
        if process:
            process.terminate()
            process.wait()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        signal.alarm(0)
        if output_file:
            output_file.close()
        if not quiet:
            _show_summary(start_time, detection_count if output else None)


def _resolve_model_path(model: Optional[str]) -> Optional[Path]:
    """
    Resolve model path from name or path.

    If model is None, auto-detect first .hef in cache/resources
    If model is a path, use it directly (NOTE: allows arbitrary paths - this is intentional
    for a local CLI tool where users are trusted to specify their own model locations)
    If model is a name, look for it in cache, then resources/
    """
    # Cache and resources directories
    cache_dir = Path.home() / ".cache" / "bugcam" / "models"
    resources_dir = Path(__file__).parent.parent.parent / "resources"

    if model is None:
        # Auto-detect first .hef file - check cache first, then resources
        if cache_dir.exists():
            hef_files = list(cache_dir.glob("*.hef"))
            if hef_files:
                return hef_files[0]

        if resources_dir.exists():
            hef_files = list(resources_dir.glob("*.hef"))
            if hef_files:
                return hef_files[0]

        return None

    # Check if it's a direct path
    # NOTE: Intentionally allows arbitrary paths for user flexibility in a local CLI tool
    model_path = Path(model)
    if model_path.exists() and model_path.suffix == ".hef":
        return model_path

    # Add .hef extension if not present
    if not model.endswith(".hef"):
        model = f"{model}.hef"

    # Look in cache directory first
    cache_model = cache_dir / model
    if cache_model.exists():
        return cache_model

    # Fall back to resources directory
    resource_model = resources_dir / model
    if resource_model.exists():
        return resource_model

    return None


def _show_startup_banner(model_path: Path, output: Optional[Path], duration: Optional[int]) -> None:
    """Display startup configuration banner."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="white")

    table.add_row("Model:", str(model_path.name))
    if output:
        table.add_row("Output:", str(output))
    if duration:
        table.add_row("Duration:", f"{duration} minutes")

    panel = Panel(table, title="[bold cyan]Insect Detection[/bold cyan]", border_style="cyan")
    console.print(panel)
    console.print()


def _show_model_not_found_help() -> None:
    """Display helpful message when no model is found."""
    cache_dir = Path.home() / ".cache" / "bugcam" / "models"

    console.print(Panel(
        "[bold red]No model found[/bold red]\n\n"
        "To download a model, run:\n"
        "[cyan]bugcam model download[/cyan]\n\n"
        f"Or place a .hef file in:\n{cache_dir}",
        border_style="red"
    ))


def _show_summary(start_time: datetime, detection_count: Optional[int]) -> None:
    """Display summary when detection stops."""
    end_time = datetime.now()
    duration = end_time - start_time

    # Format duration
    total_seconds = int(duration.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        duration_str = f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        duration_str = f"{minutes}m {seconds}s"
    else:
        duration_str = f"{seconds}s"

    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="white")

    table.add_row("Runtime:", duration_str)
    if detection_count is not None:
        table.add_row("Detections:", str(detection_count))

    panel = Panel(table, title="[bold green]Detection Complete[/bold green]", border_style="green")
    console.print(panel)
