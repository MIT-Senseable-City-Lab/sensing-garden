"""Dependency checker for bugcam."""
import typer
import subprocess
import platform
from pathlib import Path
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Check system dependencies")
console = Console()


def get_python_for_detection() -> str:
    """Get the Python interpreter to use for detection script.

    Prefers hailo-rpi5-examples venv if available, otherwise system Python.
    """
    # Check for hailo-rpi5-examples venv
    hailo_venv_python = Path.home() / "hailo-rpi5-examples" / "venv_hailo_rpi_examples" / "bin" / "python"
    if hailo_venv_python.exists():
        return str(hailo_venv_python)

    # Fall back to system Python on Linux
    if platform.system() == "Linux" and Path("/usr/bin/python3").exists():
        return "/usr/bin/python3"
    return "/usr/bin/python3"


def check_system_python_import(import_name: str) -> bool:
    """Check if a package is importable in the Python interpreter."""
    if platform.system() != "Linux":
        return False
    try:
        python_exe = get_python_for_detection()
        result = subprocess.run(
            [python_exe, "-c", f"import {import_name}"],
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


@app.callback(invoke_without_command=True)
def doctor() -> None:
    """Check all dependencies required for detection."""
    console.print("[bold cyan]bugcam dependency check[/bold cyan]\n")

    if platform.system() != "Linux":
        console.print("[yellow]Note: Detection requires Raspberry Pi (Linux)[/yellow]")
        console.print(f"Current platform: {platform.system()}\n")

    table = Table(show_header=True)
    table.add_column("Package")
    table.add_column("Status")
    table.add_column("Install command")

    all_ok = True
    deps = [
        ("gi", "python3-gi python3-gi-cairo gir1.2-gstreamer-1.0", "sudo apt install"),
        ("hailo", "hailo-all", "sudo apt install"),
        ("hailo_apps", "", "bugcam setup"),
        ("numpy", "python3-numpy", "sudo apt install"),
        ("cv2", "python3-opencv", "sudo apt install"),
    ]

    for import_name, package, cmd in deps:
        if platform.system() == "Linux":
            ok = check_system_python_import(import_name)
            if ok:
                table.add_row(import_name, "[green]OK[/green]", "")
            else:
                all_ok = False
                install_cmd = f"{cmd} {package}".strip() if package else cmd
                table.add_row(import_name, "[red]MISSING[/red]", install_cmd)
        else:
            table.add_row(import_name, "[dim]skip[/dim]", "Linux only")

    # Check for models
    cache_dir = Path.home() / ".cache" / "bugcam" / "models"
    hef_files = list(cache_dir.glob("*.hef")) if cache_dir.exists() else []
    if hef_files:
        table.add_row("model (.hef)", "[green]OK[/green]", f"{len(hef_files)} found")
    else:
        all_ok = False
        table.add_row("model (.hef)", "[red]MISSING[/red]", "bugcam models download yolov8s")

    console.print(table)
    console.print()

    if all_ok:
        console.print("[green]All dependencies satisfied![/green]")
    else:
        console.print("[yellow]Missing dependencies. Run the install commands above.[/yellow]")
