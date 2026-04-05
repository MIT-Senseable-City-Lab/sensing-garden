"""Update bugcam to the latest installed package version."""
from __future__ import annotations

import subprocess
import sys

import typer


app = typer.Typer(help="Update bugcam to the latest version", invoke_without_command=True, no_args_is_help=False)


@app.callback(invoke_without_command=True)
def update() -> None:
    """Update bugcam with pipx when available, or pip as a fallback."""
    try:
        subprocess.run(["pipx", "upgrade", "bugcam"], check=True)
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "bugcam"], check=True)
