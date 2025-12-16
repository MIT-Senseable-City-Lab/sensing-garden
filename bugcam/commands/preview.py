import typer
import subprocess
import sys
from pathlib import Path
from rich.console import Console
from ..config import get_python_for_detection, get_cache_dir
from ..utils import preflight_check, handle_numpy_error, handle_hailo_lib_error

app = typer.Typer(help="Camera preview and testing")
console = Console()

@app.callback(invoke_without_command=True)
def preview(
    duration: int = typer.Option(None, "--timeout", "-t", help="Preview timeout (seconds)"),
    hef_path: str = typer.Option(None, "--model", "-m", help="Path to .hef model file or model name"),
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
        # Check if it's a full path that exists
        hef_path_obj = Path(hef_path)
        if not hef_path_obj.exists():
            # Not a valid path, treat as model name and search for it
            model_name = hef_path if hef_path.endswith('.hef') else f"{hef_path}.hef"

            # Check cache directory first
            models_dir = get_cache_dir() / "models"
            model_files = []

            if models_dir.exists():
                model_files = list(models_dir.glob("*.hef"))

            # Fall back to resources directory
            if not model_files:
                resources_dir = Path(__file__).parent.parent.parent / "resources"
                if resources_dir.exists():
                    model_files = list(resources_dir.glob("*.hef"))

            # Find matching model
            found = False
            for model_file in model_files:
                if model_file.name == model_name:
                    hef_path = str(model_file)
                    found = True
                    break

            if not found:
                console.print(f"[red]Model '{model_name}' not found[/red]")
                console.print(f"Available models: {', '.join(m.name for m in model_files)}")
                raise typer.Exit(1)
    else:
        # Find default model if none specified
        # Check cache directory first
        models_dir = get_cache_dir() / "models"
        model_files = []

        if models_dir.exists():
            model_files = list(models_dir.glob("*.hef"))

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

    # Pre-flight dependency check
    if not preflight_check():
        console.print("[red]Missing system dependencies for detection.[/red]")
        console.print("Run [cyan]bugcam doctor[/cyan] to see what's missing.")
        raise typer.Exit(1)

    # Build command - detection.py expects --input and --hef-path arguments
    # Use system Python on Linux to access gi/hailo system packages
    # RPi AI Kit uses Hailo-8L architecture
    cmd = [get_python_for_detection(), str(detection_script), "--input", "rpi", "--arch", "hailo8l"]

    if hef_path:
        cmd.extend(["--hef-path", hef_path])

    # Show startup message
    console.print("[green]Starting camera preview[/green]")
    if hef_path:
        console.print(f"Model: [cyan]{Path(hef_path).name}[/cyan]")
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
