"""Setup command for bugcam - installs hailo_apps_infra."""
import typer
import subprocess
import sys
import platform
from pathlib import Path
from rich.console import Console

app = typer.Typer(help="Install dependencies")
console = Console()

HAILO_APPS_INFRA_URL = "git+https://github.com/hailo-ai/hailo-apps-infra.git"


def get_python_for_detection() -> str:
    """Get the Python interpreter to use."""
    hailo_venv = Path.home() / "hailo-rpi5-examples" / "venv_hailo_rpi_examples" / "bin" / "python"
    if hailo_venv.exists():
        return str(hailo_venv)
    if platform.system() == "Linux" and Path("/usr/bin/python3").exists():
        return "/usr/bin/python3"
    return sys.executable


def check_import(python_exe: str, module: str) -> bool:
    """Check if a module can be imported."""
    try:
        result = subprocess.run(
            [python_exe, "-c", f"import {module}"],
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


@app.callback(invoke_without_command=True)
def setup() -> None:
    """Install hailo_apps_infra (the only pip-installable dependency)."""
    if platform.system() != "Linux":
        console.print("[yellow]Note: bugcam detection only works on Raspberry Pi (Linux)[/yellow]")
        console.print(f"Current platform: {platform.system()}")
        raise typer.Exit(1)

    python_exe = get_python_for_detection()

    # Check if already installed
    if check_import(python_exe, "hailo_apps_infra"):
        console.print("[green]hailo_apps_infra is already installed.[/green]")
        console.print("\nRun [cyan]bugcam doctor[/cyan] to check all dependencies.")
        return

    console.print("[cyan]Installing hailo_apps_infra...[/cyan]\n")

    # Run pip install --user
    cmd = [python_exe, "-m", "pip", "install", "--user", HAILO_APPS_INFRA_URL]
    console.print(f"[dim]$ {' '.join(cmd)}[/dim]\n")

    try:
        result = subprocess.run(cmd, timeout=300)  # 5 min timeout

        if result.returncode != 0:
            console.print("\n[red]Installation failed.[/red]")
            console.print("Check the error above and try again.")
            raise typer.Exit(1)

    except subprocess.TimeoutExpired:
        console.print("\n[red]Installation timed out.[/red]")
        console.print("Check your network connection and try again.")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        raise typer.Exit(1)

    # Verify installation
    console.print("\n[cyan]Verifying installation...[/cyan]")
    if check_import(python_exe, "hailo_apps_infra"):
        console.print("[green]hailo_apps_infra: OK[/green]")
        console.print("\nRun [cyan]bugcam doctor[/cyan] to check remaining dependencies.")
    else:
        console.print("[red]hailo_apps_infra: FAILED[/red]")
        console.print("Installation completed but import failed. Check for errors above.")
        raise typer.Exit(1)
