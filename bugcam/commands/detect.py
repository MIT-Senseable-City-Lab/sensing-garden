import typer
import subprocess
import json
import signal
from pathlib import Path
from datetime import datetime
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from ..config import get_python_for_detection, get_cache_dir
from ..model_bundles import get_installed_bundles, resolve_model_path
from ..utils import preflight_check, handle_numpy_error, handle_hailo_lib_error

app = typer.Typer(help="Run insect detection")
console = Console()


@app.command()
def start(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model bundle name or path to model.hef (default: first installed bundle)"),
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

    # Pre-flight dependency check
    python_exe = get_python_for_detection()
    if not preflight_check(python_exe):
        console.print("[red]Missing system dependencies for detection.[/red]")
        console.print("Run [cyan]bugcam doctor[/cyan] to see what's missing.")
        raise typer.Exit(1)

    # Show startup banner
    if not quiet:
        _show_startup_banner(model_path, output, duration)

    # Build command - use system Python on Linux to access gi/hailo system packages
    cmd = [
        python_exe,
        str(detection_script),
        "--input", "rpi",
        "--hef-path", str(model_path),
        "--arch", "hailo8l"
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
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # Stream output
        stderr_output = []
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

        # Capture stderr
        stderr_text = process.stderr.read()
        process.wait()

        # Check for errors
        if process.returncode != 0 and stderr_text:
            # Check for missing Hailo post-process libraries
            if "Could not load lib" in stderr_text and "libyolo_hailortpp_postprocess.so" in stderr_text:
                handle_hailo_lib_error(console)
                raise typer.Exit(1)
            # Check for numpy binary incompatibility error
            elif "numpy.dtype size changed" in stderr_text or "binary incompatibility" in stderr_text:
                handle_numpy_error(console)
                raise typer.Exit(1)
            else:
                console.print(f"\n[red]Error:[/red] {stderr_text}")
                console.print("\nRun [cyan]bugcam check[/cyan] to diagnose issues.")
                raise typer.Exit(1)

    except KeyboardInterrupt:
        if not quiet:
            console.print("\n[yellow]Stopping detection...[/yellow]")
        if process:
            process.terminate()
            process.wait()
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("\nRun [cyan]bugcam check[/cyan] to diagnose issues.")
        raise typer.Exit(1)
    finally:
        signal.alarm(0)
        if output_file:
            output_file.close()
        if not quiet:
            _show_summary(start_time, detection_count if output else None)


def _resolve_model_path(model: Optional[str]) -> Optional[Path]:
    """
    Resolve model path from bundle name or explicit .hef path.
    """
    return resolve_model_path(model)


def _describe_model(model_path: Path) -> str:
    """Return a user-facing model description."""
    if model_path.name == "model.hef" and model_path.parent.name:
        return model_path.parent.name
    return model_path.name


def _show_startup_banner(model_path: Path, output: Optional[Path], duration: Optional[int]) -> None:
    """Display startup configuration banner."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="white")

    table.add_row("Model:", _describe_model(model_path))
    if output:
        table.add_row("Output:", str(output))
    if duration:
        table.add_row("Duration:", f"{duration} minutes")

    panel = Panel(table, title="[bold cyan]Insect Detection[/bold cyan]", border_style="cyan")
    console.print(panel)
    console.print()


def _show_model_not_found_help() -> None:
    """Display helpful message when no model is found."""
    models_dir = get_cache_dir() / "models"
    bundles = get_installed_bundles(require_labels=False)
    bundle_list = ", ".join(bundle.name for bundle in bundles) if bundles else "none"

    console.print(Panel(
        "[bold red]No model found[/bold red]\n\n"
        "To download a model, run:\n"
        "[cyan]bugcam models download <bundle-name>[/cyan]\n\n"
        f"Installed bundles: {bundle_list}\n"
        f"Model bundle cache:\n{models_dir}",
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
