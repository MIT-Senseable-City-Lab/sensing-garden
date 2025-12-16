"""
On-Device Detection Handler

This module defines the interface for on-device detection processing.
Developers can modify this file to customize detection behavior without
touching the underlying GStreamer/Hailo pipeline infrastructure.

The `process_detections` function is called for each frame and receives
raw detection data from the Hailo accelerator.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class Detection:
    """A single detection from the model."""
    label: str
    confidence: float
    bbox: Tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax) normalized 0-1
    track_id: Optional[int] = None


@dataclass
class DetectionResult:
    """Result from processing a frame's detections."""
    detections: List[Detection]
    frame_count: int
    should_print: bool = True
    custom_data: Optional[dict] = None


def process_detections(
    detections_raw: list,
    frame_count: int,
    hailo_module,
) -> DetectionResult:
    """
    Process raw detections from the Hailo accelerator.

    This is the main entry point for on-device detection customization.
    Modify this function to change filtering, classification, or output behavior.

    Args:
        detections_raw: List of hailo detection objects from the model
        frame_count: Current frame number
        hailo_module: Reference to hailo module for type access (e.g., HAILO_UNIQUE_ID)

    Returns:
        DetectionResult with processed detections and metadata
    """
    processed = []

    for detection in detections_raw:
        try:
            label = detection.get_label()
            confidence = detection.get_confidence()
            bbox = detection.get_bbox()

            # Extract track ID if available
            track_id = None
            track = detection.get_objects_typed(hailo_module.HAILO_UNIQUE_ID)
            if len(track) == 1:
                track_id = track[0].get_id()

            # --- CUSTOMIZE DETECTION FILTERING HERE ---
            # Example: only keep detections above confidence threshold
            # if confidence < 0.5:
            #     continue

            # Example: filter by specific labels
            # if label not in ["insect", "bee", "butterfly"]:
            #     continue

            processed.append(Detection(
                label=label,
                confidence=confidence,
                bbox=(bbox.xmin(), bbox.ymin(), bbox.xmax(), bbox.ymax()),
                track_id=track_id,
            ))
        except (AttributeError, IndexError, TypeError):
            # Skip malformed detections
            continue

    return DetectionResult(
        detections=processed,
        frame_count=frame_count,
        should_print=True,
    )


def format_detection_output(result: DetectionResult) -> str:
    """
    Format detection result for console output.

    Modify this to change how detections are printed/logged.

    Args:
        result: DetectionResult from process_detections

    Returns:
        Formatted string for output
    """
    lines = [f"Frame count: {result.frame_count}"]

    for det in result.detections:
        if det.track_id is not None:
            lines.append(
                f"Detection: ID: {det.track_id} Label: {det.label} "
                f"Confidence: {det.confidence:.2f}"
            )
        else:
            lines.append(
                f"Detection: Label: {det.label} Confidence: {det.confidence:.2f}"
            )

    return "\n".join(lines)
