import typer
import subprocess
import sys
import os
import re
import tempfile
from pathlib import Path
from rich.console import Console
from typing import Optional
from ..config import get_default_dot_ids, get_default_flick_id, get_input_storage_dir, get_output_storage_dir
from ..utils import handle_numpy_error

app = typer.Typer(help="Manage auto-start on boot")
console = Console()

SYSTEMD_SERVICE_PATH = Path("/etc/systemd/system/bugcam.service")

SERVICE_TEMPLATE_RUN = """[Unit]
Description=bugcam Edge26 Pipeline
After=multi-user.target

[Service]
Type=simple
User={user}
Group=video
WorkingDirectory={workdir}
ExecStart={bugcam_path} run --flick-id {flick_id} --dot-ids {dot_ids} --input-dir {input_dir} --output-dir {output_dir} --model {model} --mode {recording_mode} --interval {interval} --chunk-duration {chunk_duration} --bucket {bucket} --upload-poll {poll_interval}{delete_after_upload_arg}
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


@app.command()
def enable(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use"),
    bucket: Optional[str] = typer.Option(None, "--bucket", help="S3 bucket"),
    flick_id: str = typer.Option(get_default_flick_id(), "--flick-id", help="FLICK device ID"),
    dot_ids: str = typer.Option(",".join(get_default_dot_ids()), "--dot-ids", help="Comma-separated DOT IDs"),
    input_dir: Path = typer.Option(get_input_storage_dir(), "--input-dir", help="Input storage directory"),
    recording_mode: str = typer.Option("continuous", "--recording-mode", help="Recording mode: continuous or interval"),
    interval: int = typer.Option(10, "--interval", "-i", help="Minutes between recordings"),
    length: int = typer.Option(60, "--length", "-l", help="Chunk duration in seconds"),
    output_dir: Path = typer.Option(get_output_storage_dir(), "--output-dir", "-o", help="Output directory"),
    poll_interval: int = typer.Option(10, "--poll-interval", help="Upload poll interval in seconds"),
    delete_after_upload: bool = typer.Option(False, "--delete-after-upload", help="Delete uploaded non-DOT result directories"),
    start_now: bool = typer.Option(True, "--start/--no-start", help="Start service immediately"),
) -> None:
    """Enable auto-start on boot.

    Installs the full run pipeline service.
    """
    if recording_mode not in ("continuous", "interval"):
        console.print(f"[red]Invalid recording mode: {recording_mode}[/red]")
        raise typer.Exit(1)

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

        # Validate user to prevent injection
        if not _validate_username(user):
            console.print(f"[red]Error: Invalid username '{user}'[/red]")
            raise typer.Exit(1)

        # Validate paths to prevent injection
        if not _validate_path(bugcam_path):
            console.print(f"[red]Error: Invalid bugcam path[/red]")
            raise typer.Exit(1)

        if not _validate_path(workdir):
            console.print(f"[red]Error: Invalid working directory path[/red]")
            raise typer.Exit(1)
        if not _validate_model_name(flick_id):
            console.print(f"[red]Error: Invalid flick ID '{flick_id}'[/red]")
            raise typer.Exit(1)
        if dot_ids and not _validate_identifier_list(dot_ids):
            console.print(f"[red]Error: Invalid DOT IDs '{dot_ids}'[/red]")
            raise typer.Exit(1)

        if model is None:
            console.print("[red]Error: --model is required[/red]")
            raise typer.Exit(1)
        if bucket is None:
            console.print("[red]Error: --bucket is required[/red]")
            raise typer.Exit(1)
        if not _validate_model_name(bucket):
            console.print(f"[red]Error: Invalid bucket name '{bucket}'[/red]")
            raise typer.Exit(1)

        if not _validate_model_name(model):
            console.print(f"[red]Error: Invalid model name '{model}'[/red]")
            console.print("[yellow]Model name must contain only alphanumeric characters, dots, hyphens, underscores, and forward slashes[/yellow]")
            raise typer.Exit(1)

        if not _validate_path(input_dir) or not _validate_path(output_dir):
            console.print("[red]Error: Invalid input/output directory path[/red]")
            raise typer.Exit(1)

        service_content = SERVICE_TEMPLATE_RUN.format(
            user=user,
            workdir=workdir,
            bugcam_path=bugcam_path,
            flick_id=flick_id,
            dot_ids=dot_ids,
            input_dir=input_dir,
            output_dir=output_dir,
            model=model,
            recording_mode=recording_mode,
            interval=interval,
            chunk_duration=length,
            bucket=bucket,
            poll_interval=poll_interval,
            delete_after_upload_arg=" --delete-after-upload" if delete_after_upload else "",
        )
        mode_description = f"Run pipeline for {flick_id} to bucket {bucket}"

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
            result = _run_systemctl(["start", "bugcam"], check=False)

            if result.returncode != 0:
                # Check for numpy binary incompatibility
                if result.stderr and ("numpy.dtype size changed" in result.stderr or "binary incompatibility" in result.stderr):
                    handle_numpy_error(console)
                    raise typer.Exit(1)
                else:
                    console.print(f"[red]Service failed to start[/red]")
                    console.print("\nCheck logs with: [cyan]bugcam autostart logs[/cyan]")
                    console.print("Or run: [cyan]bugcam check[/cyan] to diagnose issues.")
                    raise typer.Exit(1)

            console.print("[green]✓ Service started[/green]")

        console.print("\n[bold]Service Details:[/bold]")
        console.print(f"  Binary: {bugcam_path}")
        console.print(f"  Mode:   {mode_description}")
        console.print(f"  User:   {user}")
        console.print("\n[dim]View logs with: bugcam autostart logs[/dim]")

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: {e}[/red]")
        if e.stderr:
            # Check for numpy binary incompatibility
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
    # Check if service exists
    if not SYSTEMD_SERVICE_PATH.exists():
        console.print("[yellow]Service is not installed[/yellow]")
        raise typer.Exit(0)

    # Confirm removal
    confirm = typer.confirm("Remove auto-start service?")
    if not confirm:
        console.print("[yellow]Cancelled[/yellow]")
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
    """View bugcam service logs."""
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
