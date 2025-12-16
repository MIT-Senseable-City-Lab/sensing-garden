"""Setup command for bugcam - installs Hailo dependencies."""
import typer
import subprocess
import sys
import platform
from pathlib import Path
from rich.console import Console

app = typer.Typer(help="Install dependencies")
console = Console()

HAILO_RPI5_EXAMPLES_URL = "https://github.com/hailo-ai/hailo-rpi5-examples.git"
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
    """Set up Hailo environment and compile post-processing libraries."""
    if platform.system() != "Linux":
        console.print("[yellow]Note: bugcam detection only works on Raspberry Pi (Linux)[/yellow]")
        console.print(f"Current platform: {platform.system()}")
        raise typer.Exit(1)

    hailo_examples_dir = Path.home() / "hailo-rpi5-examples"

    # Step 1: Clone hailo-rpi5-examples if needed
    if not hailo_examples_dir.exists():
        console.print("[cyan]Cloning hailo-rpi5-examples...[/cyan]")
        console.print(f"[dim]$ git clone {HAILO_RPI5_EXAMPLES_URL} {hailo_examples_dir}[/dim]\n")

        try:
            result = subprocess.run(
                ["git", "clone", HAILO_RPI5_EXAMPLES_URL, str(hailo_examples_dir)],
                timeout=120
            )
            if result.returncode != 0:
                console.print("\n[red]Clone failed.[/red]")
                raise typer.Exit(1)
            console.print("[green]Clone complete.[/green]\n")
        except subprocess.TimeoutExpired:
            console.print("\n[red]Clone timed out.[/red]")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"\n[red]Error cloning: {e}[/red]")
            raise typer.Exit(1)
    else:
        console.print(f"[green]Found hailo-rpi5-examples at {hailo_examples_dir}[/green]\n")

    # Step 2: Run install script
    install_script = hailo_examples_dir / "install.sh"
    if not install_script.exists():
        console.print(f"[red]install.sh not found at {install_script}[/red]")
        raise typer.Exit(1)

    console.print("[cyan]Running install script (this may take a few minutes)...[/cyan]")
    console.print(f"[dim]$ cd {hailo_examples_dir} && ./install.sh[/dim]\n")

    try:
        result = subprocess.run(
            ["./install.sh"],
            cwd=str(hailo_examples_dir),
            timeout=600  # 10 min timeout
        )
        if result.returncode != 0:
            console.print("\n[red]Install script failed.[/red]")
            raise typer.Exit(1)
        console.print("[green]Install script complete.[/green]\n")
    except subprocess.TimeoutExpired:
        console.print("\n[red]Install script timed out.[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[red]Error running install script: {e}[/red]")
        raise typer.Exit(1)

    # Step 3: Compile post-processing libraries
    compile_script = hailo_examples_dir / "compile_postprocess.sh"
    setup_env = hailo_examples_dir / "setup_env.sh"

    if not compile_script.exists():
        console.print(f"[red]compile_postprocess.sh not found at {compile_script}[/red]")
        raise typer.Exit(1)

    console.print("[cyan]Compiling post-processing libraries (this will take several minutes)...[/cyan]")
    console.print(f"[dim]$ cd {hailo_examples_dir} && source setup_env.sh && ./compile_postprocess.sh[/dim]\n")

    try:
        # Use bash to source setup_env.sh and run compile script
        cmd = f"cd {hailo_examples_dir} && source setup_env.sh && ./compile_postprocess.sh"
        result = subprocess.run(
            ["bash", "-c", cmd],
            timeout=900  # 15 min timeout for compilation
        )
        if result.returncode != 0:
            console.print("\n[red]Compilation failed.[/red]")
            raise typer.Exit(1)
        console.print("[green]Compilation complete.[/green]\n")
    except subprocess.TimeoutExpired:
        console.print("\n[red]Compilation timed out.[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[red]Error compiling: {e}[/red]")
        raise typer.Exit(1)

    # Step 4: Verify hailo_apps installation
    python_exe = get_python_for_detection()
    console.print("[cyan]Verifying hailo_apps installation...[/cyan]")

    if check_import(python_exe, "hailo_apps"):
        console.print("[green]hailo_apps: OK[/green]")
    else:
        console.print("[yellow]hailo_apps: Not found, attempting to install...[/yellow]\n")

        is_venv = python_exe != "/usr/bin/python3"
        if is_venv:
            cmd = [python_exe, "-m", "pip", "install", HAILO_APPS_INFRA_URL]
        else:
            cmd = [python_exe, "-m", "pip", "install", "--user", "--break-system-packages", HAILO_APPS_INFRA_URL]

        console.print(f"[dim]$ {' '.join(cmd)}[/dim]\n")

        try:
            result = subprocess.run(cmd, timeout=300)
            if result.returncode != 0:
                console.print("\n[red]hailo_apps installation failed.[/red]")
                raise typer.Exit(1)
        except subprocess.TimeoutExpired:
            console.print("\n[red]hailo_apps installation timed out.[/red]")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"\n[red]Error installing hailo_apps: {e}[/red]")
            raise typer.Exit(1)

        if check_import(python_exe, "hailo_apps"):
            console.print("[green]hailo_apps: OK[/green]")
        else:
            console.print("[red]hailo_apps installation verification failed.[/red]")
            raise typer.Exit(1)

    console.print("\n[green]Setup complete![/green]")
    console.print("Run [cyan]bugcam doctor[/cyan] to verify all dependencies.")
