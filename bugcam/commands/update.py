"""Update bugcam to the latest version from PyPI."""
from __future__ import annotations

import subprocess
import sys

import typer

from bugcam import __version__


app = typer.Typer(help="Update bugcam to the latest version", invoke_without_command=True, no_args_is_help=False)
PACKAGE_NAME = "bugcam"


@app.callback(invoke_without_command=True)
def update() -> None:
    """Update bugcam to the latest version from PyPI."""
    before_version = f"bugcam {__version__}"
    try:
        subprocess.run(["pipx", "upgrade", PACKAGE_NAME], check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE_NAME, "--break-system-packages"],
            check=True,
        )
    typer.echo(f"Updated from {before_version}")
