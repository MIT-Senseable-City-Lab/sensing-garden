import typer
import subprocess
import sys
import os
import re
import tempfile
from pathlib import Path
from rich.console import Console
from typing import Optional

app = typer.Typer(help="Manage auto-start on boot")
console = Console()

SYSTEMD_SERVICE_PATH = Path("/etc/systemd/system/bugcam.service")

SERVICE_TEMPLATE = """[Unit]
Description=bugcam Insect Detection
After=multi-user.target

[Service]
Type=simple
User={user}
Group=video
WorkingDirectory={workdir}
ExecStart={bugcam_path} detect start --model {model} --quiet
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


def _get_bugcam_path() -> Path:
    """Find the bugcam binary path."""
    # Try which bugcam first
    try:
        result = subprocess.run(
            ["which", "bugcam"],
            capture_output=True,
            text=True,
            check=True,
        )
        path = result.stdout.strip()
        if path:
            return Path(path)
    except subprocess.CalledProcessError:
        pass

    # Fallback to current Python executable
    return Path(sys.executable).parent / "bugcam"


def _validate_model_name(model: str) -> bool:
    """Validate model name contains only safe characters."""
    return bool(re.match(r'^[a-zA-Z0-9._/-]+$', model))


def _run_systemctl(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run systemctl command with sudo."""
    full_command = ["sudo", "systemctl"] + command
    return subprocess.run(
        full_command,
        capture_output=True,
        text=True,
        check=check,
    )


@app.command()
def enable(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use"),
    start_now: bool = typer.Option(True, "--start/--no-start", help="Start service immediately"),
) -> None:
    """Enable auto-start detection on boot."""
    try:
        # Get bugcam binary path
        bugcam_path = _get_bugcam_path()
        if not bugcam_path.exists():
            console.print(f"[red]Error: bugcam binary not found at {bugcam_path}[/red]")
            console.print("[yellow]Hint: Install bugcam with 'pipx install .' first[/yellow]")
            raise typer.Exit(1)

        # Get current user and working directory
        user = os.environ.get("USER", "pi")
        workdir = Path.home()

        # Default model if not specified
        if model is None:
            model = "yolov8n"

        # Validate model name to prevent command injection
        if not _validate_model_name(model):
            console.print(f"[red]Error: Invalid model name '{model}'[/red]")
            console.print("[yellow]Model name must contain only alphanumeric characters, dots, hyphens, underscores, and forward slashes[/yellow]")
            raise typer.Exit(1)

        # Generate service file content
        service_content = SERVICE_TEMPLATE.format(
            user=user,
            workdir=workdir,
            bugcam_path=bugcam_path,
            model=model,
        )

        # Write service file (requires sudo)
        console.print(f"[cyan]Creating systemd service at {SYSTEMD_SERVICE_PATH}[/cyan]")
        console.print("[yellow]This requires sudo privileges[/yellow]")

        # Write to secure temp file first, then move with sudo
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.service') as temp_file:
            temp_file.write(service_content)
            temp_service_path = temp_file.name

        try:
            subprocess.run(
                ["sudo", "mv", temp_service_path, str(SYSTEMD_SERVICE_PATH)],
                check=True,
            )
        except Exception:
            # Clean up temp file on failure
            Path(temp_service_path).unlink(missing_ok=True)
            raise

        # Reload systemd daemon
        console.print("[cyan]Reloading systemd daemon...[/cyan]")
        _run_systemctl(["daemon-reload"])

        # Enable service
        console.print("[cyan]Enabling bugcam service...[/cyan]")
        _run_systemctl(["enable", "bugcam"])

        console.print("[green]✓ Auto-start enabled successfully[/green]")

        # Optionally start immediately
        if start_now:
            console.print("[cyan]Starting bugcam service...[/cyan]")
            _run_systemctl(["start", "bugcam"])
            console.print("[green]✓ Service started[/green]")

        console.print("\n[bold]Service Details:[/bold]")
        console.print(f"  Binary: {bugcam_path}")
        console.print(f"  Model: {model}")
        console.print(f"  User: {user}")
        console.print(f"  Working Directory: {workdir}")
        console.print("\n[dim]View logs with: bugcam autostart logs[/dim]")

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e}[/red]")
        if e.stderr:
            console.print(f"[red]{e.stderr}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def disable(
    stop_now: bool = typer.Option(True, "--stop/--no-stop", help="Stop service immediately"),
) -> None:
    """Disable auto-start on boot."""
    # Check if service exists
    if not SYSTEMD_SERVICE_PATH.exists():
        console.print("[yellow]Service is not installed[/yellow]")
        raise typer.Exit(0)

    try:
        # Stop service if requested
        if stop_now:
            console.print("[cyan]Stopping bugcam service...[/cyan]")
            result = _run_systemctl(["stop", "bugcam"], check=False)
            if result.returncode == 0:
                console.print("[green]✓ Service stopped[/green]")

        # Disable service
        console.print("[cyan]Disabling bugcam service...[/cyan]")
        _run_systemctl(["disable", "bugcam"])

        # Remove service file
        console.print("[cyan]Removing service file...[/cyan]")
        subprocess.run(
            ["sudo", "rm", str(SYSTEMD_SERVICE_PATH)],
            check=True,
        )

        # Reload daemon
        _run_systemctl(["daemon-reload"])

        console.print("[green]✓ Auto-start disabled successfully[/green]")

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e}[/red]")
        if e.stderr:
            console.print(f"[red]{e.stderr}[/red]")
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show auto-start status."""
    # Check if service exists
    if not SYSTEMD_SERVICE_PATH.exists():
        console.print("[yellow]Service is not installed[/yellow]")
        console.print("[dim]Run 'bugcam autostart enable' to install[/dim]")
        raise typer.Exit(0)

    try:
        # Get service status
        result = _run_systemctl(["status", "bugcam"], check=False)

        # Print output
        console.print(result.stdout)

        # Return appropriate exit code
        raise typer.Exit(result.returncode)

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e}[/red]")
        if e.stderr:
            console.print(f"[red]{e.stderr}[/red]")
        raise typer.Exit(1)


@app.command()
def logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
) -> None:
    """View detection logs."""
    try:
        # Check if service exists
        if not SYSTEMD_SERVICE_PATH.exists():
            console.print("[yellow]Service is not installed[/yellow]")
            raise typer.Exit(0)

        # Build journalctl command
        command = ["sudo", "journalctl", "-u", "bugcam", "-n", str(lines)]
        if follow:
            command.append("-f")

        # Run journalctl
        subprocess.run(command, check=True)

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully when following logs
        console.print("\n[dim]Stopped following logs[/dim]")
        raise typer.Exit(0)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
