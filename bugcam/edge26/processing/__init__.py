"""
Processing module.

Core detection and tracking provided by BugSpot.
Classification via Hailo HEF models (edge26-specific).
"""

from .processor import VideoProcessor
from .classifier import HailoClassifier, HierarchicalClassification

# Re-exports from bugspot for convenience
from bugspot import (
    MotionDetector,
    Detection,
    InsectTracker,
    Track,
    DetectionPipeline,
    analyze_path_topology,
    check_track_consistency,
)

__all__ = [
    "VideoProcessor",
    "HailoClassifier",
    "HierarchicalClassification",
    "MotionDetector",
    "Detection",
    "InsectTracker",
    "Track",
    "DetectionPipeline",
    "analyze_path_topology",
    "check_track_consistency",
]
