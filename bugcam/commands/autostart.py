import typer
import subprocess
import sys
import os
import re
import tempfile
from pathlib import Path
from rich.console import Console
from typing import Optional
from ..runtime import select_model_reference
from ..utils import handle_numpy_error

app = typer.Typer(help="Manage auto-start on boot")
console = Console()

SYSTEMD_SERVICE_PATH = Path("/etc/systemd/system/bugcam.service")

SERVICE_TEMPLATE_RUN = """[Unit]
Description=BugCam: recording, processing, and DOT receiver
After=multi-user.target

[Service]
Type=simple
User={user}
Group=video
WorkingDirectory={workdir}
ExecStart={bugcam_path} run {run_args}
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


def _get_bugcam_path() -> Path:
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
    return bool(re.match(r'^[a-zA-Z0-9._/-]+$', model))


def _validate_path(path: Path) -> bool:
    path_str = str(path)
    if '\n' in path_str or '\r' in path_str:
        return False
    if '"' in path_str or "'" in path_str:
        return False
    if ';' in path_str or '&' in path_str or '|' in path_str:
        return False
    if '$' in path_str or '`' in path_str:
        return False
    return True


def _validate_username(user: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', user))


def _validate_identifier_list(values: str) -> bool:
    return all(_validate_model_name(value) for value in values.split(",") if value)


def _run_systemctl(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
    full_command = ["sudo", "systemctl"] + command
    return subprocess.run(
        full_command,
        capture_output=True,
        text=True,
        check=check,
    )


def _write_service_file(service_path: Path, content: str) -> None:
    """Write systemd service file using sudo."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.service') as temp_file:
        temp_file.write(content)
        temp_service_path = temp_file.name

    try:
        subprocess.run(
            ["sudo", "mv", temp_service_path, str(service_path)],
            check=True,
        )
    except Exception:
        Path(temp_service_path).unlink(missing_ok=True)
        raise


@app.command()
def enable(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use"),
    settings: Optional[Path] = typer.Option(None, "--settings", help="Bugcam settings YAML; when set, run reads all settings from it"),
    recording_mode: str = typer.Option("continuous", "--recording-mode", help="Recording mode: continuous or interval"),
    interval: int = typer.Option(10, "--interval", "-i", help="Minutes between recordings"),
    length: int = typer.Option(60, "--length", "-l", help="Chunk duration in seconds"),
    resolution: str = typer.Option("3840x2160", "--resolution", help="Recording resolution in WxH format"),
    poll_interval: int = typer.Option(10, "--poll-interval", help="Upload poll interval in seconds"),
    delete_after_upload: bool = typer.Option(
        True,
        "--delete-after-upload/--no-delete-after-upload",
        help="Clean up results after uploading",
    ),
    start_now: bool = typer.Option(True, "--start/--no-start", help="Start service immediately"),
) -> None:
    """Enable auto-start on boot.

    Installs the bugcam service which includes recording, processing,
    uploading, heartbeat, and DOT receiver.
    """
    if recording_mode not in ("continuous", "interval"):
        console.print(f"[red]Invalid recording mode: {recording_mode}[/red]")
        raise typer.Exit(1)

    if settings is not None:
        settings = settings.expanduser().resolve()
        if not settings.exists():
            console.print(f"[red]Error: settings file not found: {settings}[/red]")
            raise typer.Exit(1)
        if not _validate_path(settings):
            console.print("[red]Error: Invalid settings path[/red]")
            raise typer.Exit(1)

    try:
        bugcam_path = _get_bugcam_path()
        if not bugcam_path.exists():
            console.print(f"[red]Error: bugcam binary not found at {bugcam_path}[/red]")
            console.print("[yellow]Hint: Install bugcam with 'pipx install .' first[/yellow]")
            raise typer.Exit(1)

        user = os.environ.get("USER", "pi")
        workdir = Path.home()

        if not _validate_username(user):
            console.print(f"[red]Error: Invalid username '{user}'[/red]")
            raise typer.Exit(1)

        if not _validate_path(bugcam_path):
            console.print("[red]Error: Invalid bugcam path[/red]")
            raise typer.Exit(1)

        if not _validate_path(workdir):
            console.print("[red]Error: Invalid working directory path[/red]")
            raise typer.Exit(1)

        selected_model = select_model_reference(model)
        if not _validate_model_name(selected_model):
            console.print(f"[red]Error: Invalid model name '{selected_model}'[/red]")
            console.print("[yellow]Model name must contain only alphanumeric characters, dots, hyphens, underscores, and forward slashes[/yellow]")
            raise typer.Exit(1)

        # Build the `bugcam run` arguments. With --settings, all tunables come
        # from the settings file; otherwise bake the individual flags (legacy).
        delete_arg = "" if delete_after_upload else " --no-delete-after-upload"
        if settings is not None:
            run_args = f"--settings {settings} --model {selected_model}{delete_arg}"
        else:
            run_args = (
                f"--model {selected_model} --mode {recording_mode} --interval {interval} "
                f"--chunk-duration {length} --resolution {resolution} "
                f"--upload-poll {poll_interval}{delete_arg}"
            )

        # Create main run service (includes receiver by default)
        service_content = SERVICE_TEMPLATE_RUN.format(
            user=user,
            workdir=workdir,
            bugcam_path=bugcam_path,
            run_args=run_args,
        )

        console.print(f"[cyan]Creating systemd service at {SYSTEMD_SERVICE_PATH}[/cyan]")
        console.print("[yellow]This requires sudo privileges[/yellow]")
        _write_service_file(SYSTEMD_SERVICE_PATH, service_content)

        # Reload systemd daemon
        console.print("[cyan]Reloading systemd daemon...[/cyan]")
        _run_systemctl(["daemon-reload"])

        # Enable service
        console.print("[cyan]Enabling bugcam service...[/cyan]")
        _run_systemctl(["enable", "bugcam"])

        console.print("[green]✓ Auto-start enabled successfully[/green]")

        if start_now:
            console.print("[cyan]Starting service...[/cyan]")

            result = _run_systemctl(["start", "bugcam"], check=False)
            if result.returncode != 0:
                if result.stderr and ("numpy.dtype size changed" in result.stderr or "binary incompatibility" in result.stderr):
                    handle_numpy_error(console)
                    raise typer.Exit(1)
                else:
                    console.print("[red]Service failed to start[/red]")
                    console.print("\nCheck logs with: [cyan]bugcam autostart logs[/cyan]")
            else:
                console.print("[green]✓ Service started[/green]")

        console.print("\n[bold]Service Details:[/bold]")
        console.print(f"  Binary:  {bugcam_path}")
        console.print(f"  Model:   {selected_model}")
        console.print(f"  User:    {user}")
        console.print("\n[dim]Includes: recording, processing, upload, heartbeat, and DOT receiver[/dim]")
        console.print("[dim]View logs with: bugcam autostart logs[/dim]")

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e}[/red]")
        if e.stderr:
            if "numpy.dtype size changed" in e.stderr or "binary incompatibility" in e.stderr:
                handle_numpy_error(console)
            else:
                console.print(f"[red]{e.stderr}[/red]")
                console.print("\nRun [cyan]bugcam check[/cyan] to diagnose issues.")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("\nRun [cyan]bugcam check[/cyan] to diagnose issues.")
        raise typer.Exit(1)


@app.command()
def disable(
    stop_now: bool = typer.Option(True, "--stop/--no-stop", help="Stop service immediately"),
) -> None:
    """Disable auto-start on boot."""
    if not SYSTEMD_SERVICE_PATH.exists():
        console.print("[yellow]Service is not installed[/yellow]")
        raise typer.Exit(0)

    confirm = typer.confirm("Remove auto-start service?")
    if not confirm:
        console.print("[yellow]Cancelled[/yellow]")
        raise typer.Exit(0)

    try:
        if stop_now:
            console.print("[cyan]Stopping service...[/cyan]")
            result = _run_systemctl(["stop", "bugcam"], check=False)
            if result.returncode == 0:
                console.print("[green]✓ Service stopped[/green]")

        console.print("[cyan]Disabling service...[/cyan]")
        _run_systemctl(["disable", "bugcam"])

        console.print("[cyan]Removing service file...[/cyan]")
        subprocess.run(["sudo", "rm", str(SYSTEMD_SERVICE_PATH)], check=True)

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
    if not SYSTEMD_SERVICE_PATH.exists():
        console.print("[yellow]Service is not installed[/yellow]")
        console.print("[dim]Run 'bugcam autostart enable' to install[/dim]")
        raise typer.Exit(0)

    try:
        result = _run_systemctl(["status", "bugcam"], check=False)
        console.print(result.stdout)
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
    """View bugcam service logs."""
    try:
        if not SYSTEMD_SERVICE_PATH.exists():
            console.print("[yellow]Service is not installed[/yellow]")
            raise typer.Exit(0)

        command = ["sudo", "journalctl", "-u", "bugcam", "-n", str(lines)]
        if follow:
            command.append("-f")

        subprocess.run(command, check=True)

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped following logs[/dim]")
        raise typer.Exit(0)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
