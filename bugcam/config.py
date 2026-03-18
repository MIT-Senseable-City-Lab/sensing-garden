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
    if hailo_venv_python.is_file():
        return str(hailo_venv_python)

    # Fall back to system Python on Linux
    if platform.system() == "Linux":
        if Path("/usr/bin/python3").is_file():
            return "/usr/bin/python3"
        if Path("/usr/local/bin/python3").is_file():
            return "/usr/local/bin/python3"
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


def get_default_device_id(source_type: str) -> str:
    """Get the logical device identifier for a source type."""
    env_name = f"BUGCAM_{source_type.upper()}_DEVICE_ID"
    return os.environ.get(env_name, f"bugcam-{source_type}")


def get_edge26_model_path() -> Path:
    """Resolve the HEF model path for edge26-backed processing."""
    from .model_bundles import get_models_cache_dir, resolve_model_path

    model_ref = os.environ.get("BUGCAM_EDGE26_MODEL")
    resolved = resolve_model_path(model_ref)
    if resolved:
        return resolved

    return get_models_cache_dir() / "edge26" / "model.hef"


def get_edge26_labels_path(model_path: Path | None = None) -> Path:
    """Resolve the labels file for edge26-backed processing."""
    from .model_bundles import get_models_cache_dir, resolve_labels_path

    labels_path = os.environ.get("BUGCAM_EDGE26_LABELS")
    if labels_path:
        return Path(labels_path)

    model_ref = os.environ.get("BUGCAM_EDGE26_MODEL")
    resolved = resolve_labels_path(model_ref)
    if resolved:
        return resolved

    if model_path is not None and model_path.parent.name:
        candidate = model_path.parent / "labels.txt"
        if candidate.exists():
            return candidate
        return candidate

    return get_models_cache_dir() / "edge26" / "labels.txt"


def get_edge26_taxonomy_cache_path() -> Path:
    """Get the taxonomy cache file path."""
    cache_path = os.environ.get("BUGCAM_EDGE26_TAXONOMY_CACHE")
    if cache_path:
        return Path(cache_path)
    return get_state_dir() / "taxonomy-cache.json"


def is_edge26_classification_enabled() -> bool:
    """Return whether edge26 classification is enabled."""
    value = os.environ.get("BUGCAM_EDGE26_CLASSIFICATION", "0").lower()
    return value not in {"0", "false", "no"}


def is_edge26_continuous_tracking_enabled() -> bool:
    """Return whether edge26 continuous tracking is enabled."""
    value = os.environ.get("BUGCAM_EDGE26_CONTINUOUS_TRACKING", "1").lower()
    return value not in {"0", "false", "no"}
