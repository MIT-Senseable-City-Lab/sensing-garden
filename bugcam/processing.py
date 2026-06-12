"""BugCam edge26 configuration bridge.

Maps the resolved settings (see :mod:`bugcam.app_config`) into the nested
config dict the edge26 ``Pipeline`` consumes. All default values live in the
bundled ``settings.yaml``; this module holds no tuning literals.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .app_config import detection_keys, tracking_keys
from .config import get_edge26_taxonomy_cache_path
from .model_bundles import sha256_file

# Validation bounds for the --resolution CLI string (not tuning defaults).
MAX_CAPTURE_WIDTH = 3840
MAX_CAPTURE_HEIGHT = 2160

# The legacy --detection-config YAML uses tracker_* names for tracking params.
YAML_TO_CONFIG_KEYS = {
    "tracker_w_dist": "w_dist",
    "tracker_w_area": "w_area",
    "tracker_cost_threshold": "cost_threshold",
}


def load_detection_overrides(
    config_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse a flat detection-config YAML into (detection, tracking) overrides.

    Supports the legacy ``--detection-config`` file format whose keys are flat
    and use ``tracker_*`` names. Raises on unknown keys.
    """
    data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not data:
        return {}, {}

    det_keys = detection_keys()
    trk_keys = tracking_keys()

    detection: dict[str, Any] = {}
    tracking: dict[str, Any] = {}
    for yaml_key, value in data.items():
        if yaml_key in YAML_TO_CONFIG_KEYS:
            tracking[YAML_TO_CONFIG_KEYS[yaml_key]] = value
        elif yaml_key in det_keys:
            detection[yaml_key] = value
        elif yaml_key in trk_keys:
            tracking[yaml_key] = value
        else:
            valid_keys = sorted(det_keys | trk_keys | set(YAML_TO_CONFIG_KEYS.keys()))
            raise ValueError(
                f"Unknown key '{yaml_key}' in detection config. Valid keys: {valid_keys}"
            )
    return detection, tracking


def parse_capture_resolution(value: str) -> tuple[int, int]:
    """Parse a capture resolution in WxH format."""
    parts = value.lower().split("x")
    if len(parts) != 2:
        raise ValueError("resolution must be in WxH format")

    width = int(parts[0])
    height = int(parts[1])
    if width < 1 or height < 1:
        raise ValueError("resolution values must be positive")
    if width > MAX_CAPTURE_WIDTH or height > MAX_CAPTURE_HEIGHT:
        raise ValueError(f"resolution cannot exceed {MAX_CAPTURE_WIDTH}x{MAX_CAPTURE_HEIGHT}")
    return width, height


def build_edge26_config(
    app_config: dict[str, Any],
    *,
    flick_id: str,
    dot_ids: list[str],
    input_dir: str,
    output_dir: str,
    model_path: str,
    labels_path: str,
    model_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map the resolved central config to the edge26 pipeline config shape."""
    results_dir = Path(output_dir)
    capture = app_config["capture"]
    pipeline = app_config["pipeline"]
    output = app_config.get("output", {})
    classification = app_config.get("classification", {})

    return {
        "device": {
            "flick_id": flick_id,
            "dot_ids": dot_ids,
        },
        "paths": {
            "input_storage": str(input_dir),
            "logs_dir": str(results_dir / flick_id / "logs"),
        },
        "pipeline": {
            "enable_recording": pipeline["enable_recording"],
            "enable_processing": pipeline["enable_processing"],
            "enable_classification": pipeline["enable_classification"],
            "continuous_tracking": pipeline["continuous_tracking"],
            "detection_in_subprocess": pipeline["detection_in_subprocess"],
            "recording_mode": pipeline["recording_mode"],
            "recording_interval_minutes": pipeline["recording_interval_minutes"],
            "video_sample_interval": pipeline.get("video_sample_interval", 10),
        },
        "capture": {
            "camera_index": capture["camera_index"],
            "use_picamera": capture["use_picamera"],
            "fps": capture["fps"],
            "chunk_duration_seconds": capture["chunk_duration_seconds"],
            "resolution": list(capture["resolution"]),
            "bitrate": capture["bitrate"],
        },
        "detection": dict(app_config.get("detection", {})),
        "tracking": dict(app_config.get("tracking", {})),
        "classification": {
            "model": str(model_path),
            "labels": str(labels_path),
            "taxonomy_cache": str(get_edge26_taxonomy_cache_path()),
            "normalize": classification.get("normalize", False),
        },
        "model": dict(model_metadata or {}),
        "output": {
            "results_dir": str(output_dir),
            "save_crops": output.get("save_crops", True),
            "save_composites": output.get("save_composites", True),
        },
    }


def build_bundle_provenance(model_path: Path, labels_path: Path) -> dict[str, Any]:
    """Build technical provenance for the active bundle."""
    provenance = {
        "model_id": model_path.parent.name,
        "model_path": str(model_path),
        "labels_path": str(labels_path),
        "model_sha256": sha256_file(model_path),
        "labels_sha256": sha256_file(labels_path),
    }
    return provenance
