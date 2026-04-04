"""Setup command for BugCam."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests
import typer
from rich.console import Console

from ..config import (
    DEFAULT_API_URL,
    DEFAULT_S3_BUCKET,
    get_default_dot_ids,
    get_default_flick_id,
    get_hailo_venv_dir,
    get_python_for_detection,
    load_config,
    parse_dot_ids,
    save_config,
)

app = typer.Typer(help="Install dependencies")
console = Console()

HAILO_RPI5_EXAMPLES_URL = "https://github.com/hailo-ai/hailo-rpi5-examples.git"
HAILO_APPS_INFRA_URL = "git+https://github.com/hailo-ai/hailo-apps-infra.git"
DEFAULT_MODEL_BUNDLE = "london_141-multitask"


def check_import(python_exe: str, module: str) -> bool:
    """Check if a module can be imported."""
    try:
        result = subprocess.run(
            [python_exe, "-c", f"import {module}"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _run_command(cmd: list[str], *, cwd: str | None = None, timeout: int) -> None:
    result = subprocess.run(cmd, cwd=cwd, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")


def _install_hailo_environment() -> None:
    hailo_venv_dir = get_hailo_venv_dir()

    if hailo_venv_dir.exists():
        console.print(f"[green]Found Hailo venv at {hailo_venv_dir}[/green]\n")
        python_exe = get_python_for_detection()
        if check_import(python_exe, "hailo_apps"):
            console.print("[green]Hailo setup already complete[/green]\n")
            return

    temp_clone_dir = Path("/tmp/hailo-rpi5-examples-setup")
    if temp_clone_dir.exists():
        console.print("[yellow]Removing existing temp directory...[/yellow]")
        shutil.rmtree(temp_clone_dir)

    console.print("[cyan]Cloning hailo-rpi5-examples (shallow clone)...[/cyan]")
    console.print(f"[dim]$ git clone --depth 1 {HAILO_RPI5_EXAMPLES_URL} {temp_clone_dir}[/dim]\n")
    _run_command(["git", "clone", "--depth", "1", HAILO_RPI5_EXAMPLES_URL, str(temp_clone_dir)], timeout=120)
    console.print("[green]Clone complete.[/green]\n")

    install_script = temp_clone_dir / "install.sh"
    if not install_script.exists():
        raise FileNotFoundError(f"install.sh not found at {install_script}")

    console.print("[cyan]Running install script (this may take a few minutes)...[/cyan]")
    console.print("[dim]This will create the venv, install dependencies, and compile .so files[/dim]")
    console.print(f"[dim]$ cd {temp_clone_dir} && ./install.sh[/dim]\n")
    _run_command(["./install.sh"], cwd=str(temp_clone_dir), timeout=600)
    console.print("[green]Install script complete.[/green]\n")

    temp_venv_dir = temp_clone_dir / "venv_hailo_rpi_examples"
    if not temp_venv_dir.exists():
        raise FileNotFoundError(f"venv not found at {temp_venv_dir}")

    console.print(f"[cyan]Moving venv to {hailo_venv_dir}...[/cyan]")
    hailo_venv_dir.parent.mkdir(parents=True, exist_ok=True)
    if hailo_venv_dir.exists():
        shutil.rmtree(hailo_venv_dir)
    shutil.move(str(temp_venv_dir), str(hailo_venv_dir))
    console.print("[green]Venv moved.[/green]\n")

    python_exe = get_python_for_detection()
    console.print("[cyan]Verifying hailo_apps installation...[/cyan]")
    if not check_import(python_exe, "hailo_apps"):
        console.print("[yellow]hailo_apps: Not found, attempting to install...[/yellow]\n")
        is_venv = python_exe != "/usr/bin/python3"
        if is_venv:
            cmd = [python_exe, "-m", "pip", "install", HAILO_APPS_INFRA_URL]
        else:
            cmd = [python_exe, "-m", "pip", "install", "--user", "--break-system-packages", HAILO_APPS_INFRA_URL]
        console.print(f"[dim]$ {' '.join(cmd)}[/dim]\n")
        _run_command(cmd, timeout=300)

    if not check_import(python_exe, "hailo_apps"):
        raise RuntimeError("hailo_apps installation verification failed")
    console.print("[green]hailo_apps: OK[/green]")

    if temp_clone_dir.exists():
        console.print("[cyan]Cleaning up temporary files...[/cyan]")
        shutil.rmtree(temp_clone_dir)
        console.print("[green]Cleanup complete.[/green]\n")


def _prompt_registration_settings(existing_config: dict[str, Any]) -> dict[str, Any]:
    dot_ids_value = typer.prompt(
        "DOT IDs (comma-separated, optional)",
        default=",".join(parse_dot_ids(existing_config.get("dot_ids")) or get_default_dot_ids()),
        show_default=False,
    )
    return {
        "api_url": typer.prompt("API URL", default=str(existing_config.get("api_url") or DEFAULT_API_URL)),
        "setup_code": typer.prompt("Setup code", hide_input=True),
        "device_name": typer.prompt("Device name", default=str(existing_config.get("device_name") or platform.node() or "bugcam-pi")),
        "flick_id": typer.prompt("FLICK ID", default=str(existing_config.get("flick_id") or get_default_flick_id())),
        "dot_ids": parse_dot_ids(dot_ids_value),
    }


def _register_device(api_url: str, setup_code: str, device_name: str) -> dict[str, Any]:
    response = requests.post(
        f"{api_url.rstrip('/')}/devices/register",
        json={"setup_code": setup_code, "device_name": device_name},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    required_fields = ("device_id", "api_key", "device_name", "created")
    missing_fields = [field for field in required_fields if field not in payload]
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise ValueError(f"Registration response missing fields: {joined}")
    return payload


def _download_default_model() -> None:
    cmd = [sys.executable, "-m", "bugcam.cli", "models", "download", DEFAULT_MODEL_BUNDLE]
    console.print(f"[cyan]Downloading default model[/cyan] {DEFAULT_MODEL_BUNDLE}")
    console.print(f"[dim]$ {' '.join(cmd)}[/dim]\n")
    _run_command(cmd, timeout=300)


def _run_status_check() -> None:
    cmd = [sys.executable, "-m", "bugcam.cli", "status"]
    console.print("[cyan]Running bugcam status...[/cyan]")
    console.print(f"[dim]$ {' '.join(cmd)}[/dim]\n")
    result = subprocess.run(cmd, timeout=60)
    if result.returncode != 0:
        console.print("[yellow]Status check reported issues. Review the output above.[/yellow]")


@app.callback(invoke_without_command=True)
def setup() -> None:
    """Install Hailo dependencies, register the device, and save local config."""
    if platform.system() != "Linux":
        console.print("[yellow]Note: bugcam detection only works on Raspberry Pi (Linux)[/yellow]")
        console.print(f"Current platform: {platform.system()}")
        raise typer.Exit(1)

    try:
        _install_hailo_environment()
        existing_config = load_config()
        settings = _prompt_registration_settings(existing_config)
        registration = _register_device(settings["api_url"], settings["setup_code"], settings["device_name"])
        saved_config = {
            **existing_config,
            "api_url": settings["api_url"].rstrip("/"),
            "api_key": registration["api_key"],
            "device_id": registration["device_id"],
            "device_name": registration["device_name"],
            "s3_bucket": str(existing_config.get("s3_bucket") or DEFAULT_S3_BUCKET),
            "flick_id": settings["flick_id"],
            "dot_ids": settings["dot_ids"],
        }
        save_config(saved_config)
        console.print(f"[green]Saved config to {saved_config['device_name']} ({saved_config['device_id']})[/green]\n")
        _download_default_model()
        _run_status_check()
        console.print("[green]Setup complete![/green]")
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
