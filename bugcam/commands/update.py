"""Update bugcam to the latest installed package version."""
from __future__ import annotations

import subprocess
import sys

import typer

from bugcam import __version__


app = typer.Typer(help="Update bugcam to the latest version", invoke_without_command=True, no_args_is_help=False)
GIT_INSTALL_URL = "git+https://github.com/daydemir/sensing-garden.git@bugcam-cli"


def _read_cli_version(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@app.callback(invoke_without_command=True)
def update() -> None:
    """Update bugcam from the git branch used for device installs."""
    before_version = f"bugcam {__version__}"
    try:
        subprocess.run(["pipx", "install", "--force", GIT_INSTALL_URL], check=True)
        after_version = _read_cli_version(["bugcam", "--version"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", GIT_INSTALL_URL], check=True)
        after_version = _read_cli_version([sys.executable, "-m", "bugcam.cli", "--version"])
    typer.echo(f"{before_version} -> {after_version}")
