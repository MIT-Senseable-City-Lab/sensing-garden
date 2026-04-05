"""BugCam edge26 configuration bridge."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import (
    get_edge26_taxonomy_cache_path,
)
from .model_bundles import sha256_file

DEFAULT_CAPTURE_RESOLUTION = (1080, 1080)
MAX_CAPTURE_WIDTH = 3840
MAX_CAPTURE_HEIGHT = 2160

EDGE26_DETECTION_DEFAULTS = {
    "gmm_history": 500,
    "gmm_var_threshold": 16,
    "morph_kernel_size": 3,
    "min_area": 200,
    "max_area": 40000,
    "min_density": 3.0,
    "min_solidity": 0.55,
    "min_largest_blob_ratio": 0.80,
    "max_num_blobs": 5,
    "min_motion_ratio": 0.15,
    "max_frame_jump": 100,
    "max_area_change_ratio": 3.0,
    "min_path_points": 10,
    "min_displacement": 50,
    "max_revisit_ratio": 0.30,
    "min_progression_ratio": 0.70,
    "max_directional_variance": 0.90,
    "revisit_radius": 50,
}

EDGE26_TRACKING_DEFAULTS = {
    "w_dist": 0.6,
    "w_area": 0.4,
    "cost_threshold": 0.3,
    "max_lost_frames": 45,
}


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
    flick_id: str,
    dot_ids: list[str],
    input_dir: str,
    output_dir: str,
    model_path: str,
    labels_path: str,
    recording_mode: str = "continuous",
    recording_interval: int = 5,
    chunk_duration: int = 60,
    fps: int = 30,
    resolution: tuple[int, int] = DEFAULT_CAPTURE_RESOLUTION,
    enable_recording: bool = True,
    enable_processing: bool = True,
    enable_classification: bool = True,
    continuous_tracking: bool = True,
    model_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the edge26 pipeline config from BugCam-owned settings."""
    results_dir = Path(output_dir)
    return {
        "device": {
            "flick_id": flick_id,
            "dot_ids": dot_ids,
        },
        "paths": {
            "input_storage": input_dir,
            "logs_dir": str(results_dir / flick_id / "logs"),
        },
        "pipeline": {
            "enable_recording": enable_recording,
            "enable_processing": enable_processing,
            "enable_classification": enable_classification,
            "continuous_tracking": continuous_tracking,
            "recording_mode": recording_mode,
            "recording_interval_minutes": recording_interval,
        },
        "capture": {
            "camera_index": 0,
            "use_picamera": True,
            "fps": fps,
            "chunk_duration_seconds": chunk_duration,
            "resolution": list(resolution),
        },
        "detection": dict(EDGE26_DETECTION_DEFAULTS),
        "tracking": dict(EDGE26_TRACKING_DEFAULTS),
        "classification": {
            "model": model_path,
            "labels": labels_path,
            "taxonomy_cache": str(get_edge26_taxonomy_cache_path()),
            "normalize": False,
        },
        "model": dict(model_metadata or {}),
        "output": {
            "results_dir": output_dir,
            "save_crops": True,
            "save_composites": True,
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
