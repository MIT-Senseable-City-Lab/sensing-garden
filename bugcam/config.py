"""Shared configuration utilities for bugcam."""
import os
import sys
import platform
from pathlib import Path


def get_hailo_venv_dir() -> Path:
    """Get the directory for the Hailo venv."""
    return Path.home() / ".local" / "share" / "bugcam" / "hailo-venv"


def get_python_for_detection() -> str:
    """Get the Python interpreter to use for detection script.

    Prefers hailo venv if available, otherwise system Python.
    """
    # Check for hailo venv
    hailo_venv_python = get_hailo_venv_dir() / "bin" / "python"
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


def get_state_dir() -> Path:
    """Get the state directory for bugcam, respecting XDG_DATA_HOME."""
    state_dir = os.environ.get("BUGCAM_STATE_DIR")
    if state_dir:
        return Path(state_dir)

    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data) / "bugcam"
    return Path.home() / ".local" / "share" / "bugcam"


def get_jobs_dir() -> Path:
    """Get the job state root directory."""
    return get_state_dir() / "jobs"


def get_incoming_dir() -> Path:
    """Get the managed incoming media directory."""
    return get_state_dir() / "incoming"


def get_outputs_dir() -> Path:
    """Get the processed output directory."""
    return get_state_dir() / "outputs"


def get_iphone_watch_dir() -> Path:
    """Get the watched directory for iPhone-origin media."""
    watch_dir = os.environ.get("BUGCAM_IPHONE_WATCH_DIR")
    if watch_dir:
        return Path(watch_dir)
    return get_state_dir() / "incoming-iphone"


def get_recordings_dir() -> Path:
    """Get the default RPi recordings directory."""
    record_dir = os.environ.get("BUGCAM_RECORDINGS_DIR")
    if record_dir:
        return Path(record_dir)
    return Path.home() / "bugcam-videos"
