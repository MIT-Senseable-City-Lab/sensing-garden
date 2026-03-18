"""BugCam processing adapter layer backed by vendored edge26 runtime."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .config import (
    get_default_device_id,
    get_edge26_labels_path,
    get_edge26_model_path,
    get_edge26_taxonomy_cache_path,
    get_outputs_dir,
    is_edge26_classification_enabled,
    is_edge26_continuous_tracking_enabled,
)
from .edge26_runtime import ResultsWriter, VideoProcessor

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


def build_edge26_config(output_root: Path | None = None) -> dict[str, Any]:
    """Build the edge26 runtime config from BugCam-owned settings."""
    model_path = get_edge26_model_path()
    labels_path = get_edge26_labels_path(model_path)
    return {
        "device": {
            "flick_id": get_default_device_id("rpi"),
            "dot_ids": [],
        },
        "pipeline": {
            "enable_recording": False,
            "enable_processing": True,
            "enable_classification": is_edge26_classification_enabled(),
            "continuous_tracking": is_edge26_continuous_tracking_enabled(),
        },
        "detection": dict(EDGE26_DETECTION_DEFAULTS),
        "tracking": dict(EDGE26_TRACKING_DEFAULTS),
        "classification": {
            "model": str(model_path),
            "labels": str(labels_path),
            "taxonomy_cache": str(get_edge26_taxonomy_cache_path()),
            "normalize": False,
        },
        "output": {
            "results_dir": str(output_root or get_outputs_dir()),
            "save_crops": True,
            "save_composites": True,
        },
    }


@dataclass
class Edge26ProcessResult:
    """Structured summary returned to the jobs pipeline."""

    processor: str
    job_id: str
    source_type: str
    logical_device_id: str
    input_media: str
    output_dir: str
    results_path: str
    summary: dict[str, Any]
    tracks: int
    confirmed_tracks: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "processor": self.processor,
            "job_id": self.job_id,
            "source_type": self.source_type,
            "logical_device_id": self.logical_device_id,
            "input_media": self.input_media,
            "output_dir": self.output_dir,
            "results_path": self.results_path,
            "summary": self.summary,
            "tracks": self.tracks,
            "confirmed_tracks": self.confirmed_tracks,
        }


class Edge26ProcessorAdapter:
    """BugCam adapter around vendored edge26 processor and writer."""

    name = "edge26"

    def __init__(self, output_root: Path | None = None):
        self.config = build_edge26_config(output_root=output_root)
        self.output_root = output_root or get_outputs_dir()
        self.runtime = VideoProcessor(self.config)
        self.writer = ResultsWriter(self.output_root)

    def process(self, media_path: Path, output_dir: Path, job: dict[str, Any]) -> dict[str, Any]:
        results = self.runtime.process_video(media_path, output_dir)
        output_paths = self.writer.write_results(results=results, output_dir=output_dir)
        summary = results.get("summary", {})
        return Edge26ProcessResult(
            processor=self.name,
            job_id=job["job_id"],
            source_type=job["source_type"],
            logical_device_id=job["logical_device_id"],
            input_media=str(media_path),
            output_dir=str(output_dir),
            results_path=str(output_paths["json"]),
            summary=summary,
            tracks=summary.get("total_tracks", 0),
            confirmed_tracks=summary.get("confirmed_tracks", 0),
        ).as_dict()

    def reset(self) -> None:
        self.runtime.reset_tracker()

    def clear(self) -> None:
        self.runtime.clear_video_detections()


class ProcessorManager:
    """Manage one persistent edge26-backed processor across queued jobs."""

    def __init__(self):
        self._processor: Optional[Edge26ProcessorAdapter] = None
        self._continuity_key: Optional[str] = None

    def process(self, media_path: Path, output_dir: Path, job: dict[str, Any]) -> dict[str, Any]:
        continuity_key = job.get("continuity_key") or job.get("logical_device_id") or job["source_type"]
        if self._processor is None:
            self._processor = Edge26ProcessorAdapter(output_root=get_outputs_dir())
        elif not is_edge26_continuous_tracking_enabled() or continuity_key != self._continuity_key:
            self._processor.reset()

        self._continuity_key = continuity_key
        try:
            return self._processor.process(media_path, output_dir, job)
        finally:
            self._processor.clear()

    def reset(self) -> None:
        if self._processor is not None:
            self._processor.reset()
        self._continuity_key = None


_PROCESSOR_MANAGER: Optional[ProcessorManager] = None


def get_processor_manager() -> ProcessorManager:
    """Return the process-wide processor manager."""
    global _PROCESSOR_MANAGER
    if _PROCESSOR_MANAGER is None:
        _PROCESSOR_MANAGER = ProcessorManager()
    return _PROCESSOR_MANAGER


def reset_processor_manager() -> None:
    """Reset the process-wide processor manager."""
    global _PROCESSOR_MANAGER
    if _PROCESSOR_MANAGER is not None:
        _PROCESSOR_MANAGER.reset()
    _PROCESSOR_MANAGER = None
