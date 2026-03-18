import typer
import subprocess
import sys
from pathlib import Path
from rich.console import Console
from ..config import get_python_for_detection
from ..model_bundles import get_installed_bundles, resolve_model_path
from ..utils import preflight_check, handle_numpy_error, handle_hailo_lib_error

app = typer.Typer(help="Camera preview and testing")
console = Console()

@app.callback(invoke_without_command=True)
def preview(
    duration: int = typer.Option(None, "--timeout", "-t", help="Preview timeout (seconds)"),
    hef_path: str = typer.Option(None, "--model", "-m", help="Model bundle name or path to model.hef"),
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

    # Resolve model path
    if hef_path is not None:
        resolved_model = resolve_model_path(hef_path)
        if resolved_model is None:
            installed = get_installed_bundles(require_labels=False)
            available = ", ".join(bundle.name for bundle in installed) if installed else "none"
            console.print(f"[red]Model '{hef_path}' not found[/red]")
            console.print(f"Available bundles: {available}")
            raise typer.Exit(1)
        hef_path = str(resolved_model)
    else:
        resolved_model = resolve_model_path(None)
        if resolved_model:
            hef_path = str(resolved_model)
        else:
            console.print("[yellow]No model found[/yellow]")
            console.print("Download a model with: [cyan]bugcam models download <bundle-name>[/cyan]")
            console.print("Running without detection overlay\n")

    # Pre-flight dependency check
    python_exe = get_python_for_detection()
    if not preflight_check(python_exe):
        console.print("[red]Missing system dependencies for detection.[/red]")
        console.print("Run [cyan]bugcam doctor[/cyan] to see what's missing.")
        raise typer.Exit(1)

    # Build command - detection.py expects --input and --hef-path arguments
    # Use system Python on Linux to access gi/hailo system packages
    # RPi AI Kit uses Hailo-8L architecture
    cmd = [python_exe, str(detection_script), "--input", "rpi", "--arch", "hailo8l"]

    if hef_path:
        cmd.extend(["--hef-path", hef_path])

    # Show startup message
    console.print("[green]Starting camera preview[/green]")
    if hef_path:
        hef_file = Path(hef_path)
        model_name = hef_file.parent.name if hef_file.name == "model.hef" and hef_file.parent.name else hef_file.name
        console.print(f"Model: [cyan]{model_name}[/cyan]")
    console.print("Press [cyan]Ctrl+C[/cyan] to stop\n")

    process = None
    try:
        process = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
        _, stderr = process.communicate()

        # Check for errors
        if process.returncode != 0 and stderr:
            # Check for missing Hailo post-process libraries
            if "Could not load lib" in stderr and "libyolo_hailortpp_postprocess.so" in stderr:
                handle_hailo_lib_error(console)
                sys.exit(1)
            # Check for numpy binary incompatibility error
            elif "numpy.dtype size changed" in stderr or "binary incompatibility" in stderr:
                handle_numpy_error(console)
                sys.exit(1)
            else:
                # Show actual error
                console.print(f"[red]Error:[/red] {stderr}")
                console.print("\nRun [cyan]bugcam check[/cyan] to diagnose issues.")

        sys.exit(process.returncode)
    except KeyboardInterrupt:
        console.print("\n[green]Preview stopped[/green]")
        if process:
            process.terminate()
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("\nRun [cyan]bugcam check[/cyan] to diagnose issues.")
        sys.exit(1)
