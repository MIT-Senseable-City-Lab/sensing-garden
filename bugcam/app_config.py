"""Centralised bugcam settings resolver.

A single bundled ``settings.yaml`` holds every operational default. This module
loads it and merges, in increasing order of precedence:

    bundled settings.yaml
      < ~/.config/bugcam/config.json   (device identity/paths from `bugcam setup`)
      < user --settings file
      < BUGCAM_* environment variables
      < explicit CLI flags             (applied by the command layer)

The result is one fully-resolved nested dict that every command builds on.
"""
from __future__ import annotations

import copy
import os
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml


def get_bundled_settings_path() -> Path:
    """Path to the bundled settings file shipped inside the package."""
    import bugcam

    return Path(resources.files(bugcam) / "settings.yaml")


@lru_cache(maxsize=1)
def get_bundled_config() -> dict[str, Any]:
    """Load (and cache) the bundled settings."""
    data = yaml.safe_load(get_bundled_settings_path().read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("bundled settings.yaml must be a mapping")
    return data


def detection_keys() -> set[str]:
    """Valid detection parameter keys (derived from the bundled config)."""
    return set(get_bundled_config().get("detection", {}).keys())


def tracking_keys() -> set[str]:
    """Valid tracking parameter keys (derived from the bundled config)."""
    return set(get_bundled_config().get("tracking", {}).keys())


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if value is None:
            continue
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must be a mapping: {path}")
    return data


def _config_json_layer() -> dict[str, Any]:
    """Map the legacy ~/.config/bugcam/config.json into the nested schema."""
    from .config import load_config

    flat = load_config()
    if not flat:
        return {}

    device: dict[str, Any] = {}
    for key in ("api_url", "api_key", "s3_bucket", "flick_id", "dot_ids"):
        if flat.get(key) not in (None, ""):
            device[key] = flat[key]
    if "device_id" in flat and "flick_id" not in device:
        device["flick_id"] = flat["device_id"]

    paths: dict[str, Any] = {}
    for key in ("state_dir", "input_dir", "output_dir", "pending_dir"):
        if flat.get(key):
            paths[key] = flat[key]

    layer: dict[str, Any] = {}
    if device:
        layer["device"] = device
    if paths:
        layer["paths"] = paths
    return layer


def _env_layer() -> dict[str, Any]:
    """Map BUGCAM_* environment variables into the nested schema."""
    env = os.environ
    device: dict[str, Any] = {}
    paths: dict[str, Any] = {}
    pipeline: dict[str, Any] = {}
    receiver: dict[str, Any] = {}

    if env.get("BUGCAM_FLICK_ID"):
        device["flick_id"] = env["BUGCAM_FLICK_ID"]
    if env.get("BUGCAM_DOT_IDS"):
        device["dot_ids"] = [v.strip() for v in env["BUGCAM_DOT_IDS"].split(",") if v.strip()]

    for env_key, path_key in (
        ("BUGCAM_STATE_DIR", "state_dir"),
        ("BUGCAM_INPUT_DIR", "input_dir"),
        ("BUGCAM_OUTPUT_DIR", "output_dir"),
        ("BUGCAM_PENDING_DIR", "pending_dir"),
    ):
        if env.get(env_key):
            paths[path_key] = env[env_key]

    if env.get("BUGCAM_EDGE26_CLASSIFICATION") is not None and env.get("BUGCAM_EDGE26_CLASSIFICATION") != "":
        pipeline["enable_classification"] = env["BUGCAM_EDGE26_CLASSIFICATION"].lower() not in {"0", "false", "no"}
    if env.get("BUGCAM_EDGE26_CONTINUOUS_TRACKING") is not None and env.get("BUGCAM_EDGE26_CONTINUOUS_TRACKING") != "":
        pipeline["continuous_tracking"] = env["BUGCAM_EDGE26_CONTINUOUS_TRACKING"].lower() not in {"0", "false", "no"}

    if env.get("BUGCAM_RECEIVER_HOST"):
        receiver["host"] = env["BUGCAM_RECEIVER_HOST"]
    if env.get("BUGCAM_RECEIVER_PORT"):
        receiver["port"] = int(env["BUGCAM_RECEIVER_PORT"])

    layer: dict[str, Any] = {}
    if device:
        layer["device"] = device
    if paths:
        layer["paths"] = paths
    if pipeline:
        layer["pipeline"] = pipeline
    if receiver:
        layer["receiver"] = receiver
    return layer


def load_app_config(user_settings_path: Path | None = None) -> dict[str, Any]:
    """Resolve the settings by merging all layers in precedence order.

    CLI flags are NOT applied here; the command layer overlays explicitly-set
    flags on top of the returned dict.
    """
    config = copy.deepcopy(get_bundled_config())
    config = deep_merge(config, _config_json_layer())
    if user_settings_path is not None:
        config = deep_merge(config, _load_yaml_file(Path(user_settings_path)))
    config = deep_merge(config, _env_layer())
    return config


def apply_overrides(config: dict[str, Any], section: str, **overrides: Any) -> None:
    """Overlay explicitly-provided (non-None) values onto a config section."""
    target = config.setdefault(section, {})
    for key, value in overrides.items():
        if value is not None:
            target[key] = value
