"""Shared configuration utilities for bugcam."""
import os
import sys
import platform
from pathlib import Path


def get_python_for_detection() -> str:
    """Get the Python interpreter to use for detection script.

    Prefers hailo-rpi5-examples venv if available, otherwise system Python.
    """
    # Check for hailo-rpi5-examples venv
    hailo_venv_python = Path.home() / "hailo-rpi5-examples" / "venv_hailo_rpi_examples" / "bin" / "python"
    if hailo_venv_python.exists():
        return str(hailo_venv_python)

    # Fall back to system Python on Linux
    if platform.system() == "Linux" and Path("/usr/bin/python3").exists():
        return "/usr/bin/python3"
    return sys.executable


def get_cache_dir() -> Path:
    """Get the cache directory for bugcam, respecting XDG_CACHE_HOME."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "bugcam"
    return Path.home() / ".cache" / "bugcam"


def get_hailo_examples_dir() -> Path:
    """Get the hailo-rpi5-examples directory, respecting HAILO_EXAMPLES_PATH env var."""
    env_path = os.environ.get("HAILO_EXAMPLES_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / "hailo-rpi5-examples"
