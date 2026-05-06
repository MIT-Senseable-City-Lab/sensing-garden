"""BugCam CLI - entry point."""
import sys
import site


def _ensure_system_packages_access():
    """Make system dist-packages importable before importing commands.

    System packages like hailo_platform (installed via apt) may not be
    in the Python path when running from a virtual environment (e.g., pipx).
    This function ensures they are accessible.
    """
    system_dist_packages = "/usr/lib/python3/dist-packages"

    # Check if hailo_platform is already importable
    try:
        import hailo_platform  # noqa: F401
        return  # Already works
    except ImportError:
        pass

    # Add system dist-packages to path
    if system_dist_packages not in sys.path:
        site.addsitedir(system_dist_packages)


# Ensure system packages are accessible BEFORE importing commands
_ensure_system_packages_access()

import typer
from rich.console import Console
from bugcam import __version__
from bugcam.commands import autostart, dot_info, environment, heartbeat, models, process, receive, record, run, setup, status, update, upload

app = typer.Typer(
    name="bugcam",
    help="CLI for Raspberry Pi insect detection with Hailo AI",
    add_completion=False,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        print(f"bugcam {__version__}")
        raise typer.Exit()

# Register subcommand groups
app.add_typer(models.app, name="models")
app.add_typer(record.app, name="record")
app.add_typer(autostart.app, name="autostart")
app.add_typer(setup.app, name="setup")
app.add_typer(status.app, name="status")
app.add_typer(run.app, name="run")
app.add_typer(process.app, name="process")
app.add_typer(upload.app, name="upload")
app.add_typer(heartbeat.app, name="heartbeat")
app.add_typer(environment.app, name="environment")
app.add_typer(dot_info.app, name="dot-info")
app.add_typer(update.app, name="update")
app.add_typer(receive.app, name="receive")

@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show the installed bugcam version and exit",
    ),
) -> None:
    """bugcam - Raspberry Pi insect detection CLI"""
    pass

if __name__ == "__main__":
    app()
