"""Vendored edge26 video processor for BugCam job execution."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .classifier import HailoClassifier, HierarchicalClassification

logger = logging.getLogger(__name__)

_NA_PREDICTION = {
    "family": "N/A",
    "genus": "N/A",
    "species": "N/A",
    "family_confidence": None,
    "genus_confidence": None,
    "species_confidence": None,
}


class VideoProcessor:
    """Vendored edge26 processor with BugCam-owned orchestration outside."""

    def __init__(self, config: dict):
        try:
            from bugspot import DetectionPipeline
        except ImportError as exc:
            raise RuntimeError("bugspot is required for edge26-backed processing") from exc

        self.config = config
        self.detection_config = config.get("detection", {})
        self.classification_config = config.get("classification", {})
        self.tracking_config = config.get("tracking", {})
        self.output_config = config.get("output", {})

        bugspot_config = dict(self.detection_config)
        bugspot_config["max_lost_frames"] = self.tracking_config.get("max_lost_frames", 45)
        bugspot_config["tracker_w_dist"] = self.tracking_config.get("w_dist", 0.6)
        bugspot_config["tracker_w_area"] = self.tracking_config.get("w_area", 0.4)
        bugspot_config["tracker_cost_threshold"] = self.tracking_config.get("cost_threshold", 0.3)

        self._pipeline = DetectionPipeline(bugspot_config)
        pipeline_config = config.get("pipeline", {})
        self.enable_classification = pipeline_config.get("enable_classification", True)
        self.continuous_tracking = pipeline_config.get("continuous_tracking", True)
        self._classifier: Optional[HailoClassifier] = None

    def process_video(self, video_path: Path, output_dir: Path) -> Dict:
        logger.info("Processing video: %s", video_path.name)
        save_composites_dir = str(output_dir / "composites") if self.output_config.get("save_composites", True) else None
        save_crops_dir = str(output_dir / "crops") if self.output_config.get("save_crops", True) else None

        result = self._pipeline.process_video(
            str(video_path),
            extract_crops=True,
            render_composites=save_composites_dir is not None,
            save_crops_dir=save_crops_dir,
            save_composites_dir=save_composites_dir,
        )

        track_classifications: Dict[str, List[HierarchicalClassification]] = {}
        if self.enable_classification and result.confirmed_tracks:
            if self._classifier is None:
                self._classifier = HailoClassifier(self.classification_config)
            for track_id, track in result.confirmed_tracks.items():
                classifications = []
                for frame_num, crop in track.crops:
                    classification = self._classifier.classify(crop)
                    classifications.append(classification)
                    for det in result.all_detections:
                        if det["track_id"] == track_id and det["frame_number"] == frame_num:
                            det["family"] = classification.family
                            det["genus"] = classification.genus
                            det["species"] = classification.species
                            det["family_confidence"] = classification.family_confidence
                            det["genus_confidence"] = classification.genus_confidence
                            det["species_confidence"] = classification.species_confidence
                            break
                if classifications:
                    track_classifications[track_id] = classifications

        if self.enable_classification:
            aggregated = self._hierarchical_aggregation(result, track_classifications)
        else:
            aggregated = self._detection_only_aggregation(result)

        return self._build_output(
            video_path=video_path,
            video_timestamp=self._parse_timestamp(video_path.stem),
            pipeline_result=result,
            aggregated=aggregated,
        )

    def _hierarchical_aggregation(self, result, track_classifications: Dict[str, List[HierarchicalClassification]]) -> List[Dict]:
        results = []
        for track_id, track in result.confirmed_tracks.items():
            classifications = track_classifications.get(track_id, [])
            if not classifications:
                continue
            final_pred = self._classifier.hierarchical_aggregate(classifications)
            if not final_pred:
                continue
            results.append(
                {
                    "track_id": track_id,
                    "num_detections": track.num_detections,
                    "first_frame_time": track.first_frame_time,
                    "last_frame_time": track.last_frame_time,
                    "duration": track.duration,
                    "final_family": final_pred["family"],
                    "final_genus": final_pred["genus"],
                    "final_species": final_pred["species"],
                    "family_confidence": final_pred["family_confidence"],
                    "genus_confidence": final_pred["genus_confidence"],
                    "species_confidence": final_pred["species_confidence"],
                    "passes_topology": True,
                    **track.topology_metrics,
                }
            )
        return results

    def _detection_only_aggregation(self, result) -> List[Dict]:
        results = []
        for track_id, track in result.confirmed_tracks.items():
            results.append(
                {
                    "track_id": track_id,
                    "num_detections": track.num_detections,
                    "first_frame_time": track.first_frame_time,
                    "last_frame_time": track.last_frame_time,
                    "duration": track.duration,
                    "final_family": _NA_PREDICTION["family"],
                    "final_genus": _NA_PREDICTION["genus"],
                    "final_species": _NA_PREDICTION["species"],
                    "family_confidence": _NA_PREDICTION["family_confidence"],
                    "genus_confidence": _NA_PREDICTION["genus_confidence"],
                    "species_confidence": _NA_PREDICTION["species_confidence"],
                    "passes_topology": True,
                    **track.topology_metrics,
                }
            )
        return results

    def _build_output(self, video_path: Path, video_timestamp: Optional[datetime], pipeline_result, aggregated: List[Dict]) -> Dict:
        tracks_data = []
        for entry in aggregated:
            track_id = entry["track_id"]
            track_dets = [d for d in pipeline_result.all_detections if d["track_id"] == track_id]
            frames = []
            for det in track_dets:
                frame_data = {
                    "frame_number": det["frame_number"],
                    "timestamp_seconds": det["frame_time_seconds"],
                    "bbox": det["bbox"],
                }
                if "species" in det:
                    frame_data["prediction"] = {
                        "family": det["family"],
                        "genus": det["genus"],
                        "species": det["species"],
                        "family_confidence": det["family_confidence"],
                        "genus_confidence": det["genus_confidence"],
                        "species_confidence": det["species_confidence"],
                    }
                elif not self.enable_classification:
                    frame_data["prediction"] = dict(_NA_PREDICTION)
                frames.append(frame_data)

            tracks_data.append(
                {
                    "track_id": track_id,
                    "final_prediction": {
                        "family": entry["final_family"],
                        "genus": entry["final_genus"],
                        "species": entry["final_species"],
                        "family_confidence": entry["family_confidence"],
                        "genus_confidence": entry["genus_confidence"],
                        "species_confidence": entry["species_confidence"],
                    },
                    "num_detections": entry["num_detections"],
                    "first_seen_seconds": entry["first_frame_time"],
                    "last_seen_seconds": entry["last_frame_time"],
                    "duration_seconds": entry["duration"],
                    "topology_metrics": {
                        key: entry.get(key)
                        for key in ["net_displacement", "revisit_ratio", "progression_ratio", "directional_variance"]
                    },
                    "frames": frames,
                }
            )

        video_info = pipeline_result.video_info
        return {
            "video_file": video_path.name,
            "video_timestamp": video_timestamp.isoformat() if video_timestamp else None,
            "processing_timestamp": datetime.now().isoformat(),
            "video_info": {
                "fps": video_info["fps"],
                "total_frames": video_info["total_frames"],
                "duration_seconds": video_info["duration"],
            },
            "summary": {
                "total_detections": len(pipeline_result.all_detections),
                "total_tracks": len(pipeline_result.track_paths),
                "confirmed_tracks": len(pipeline_result.confirmed_tracks),
                "unconfirmed_tracks": len(pipeline_result.track_paths) - len(pipeline_result.confirmed_tracks),
            },
            "tracks": tracks_data,
        }

    def _parse_timestamp(self, filename_stem: str) -> Optional[datetime]:
        try:
            parts = filename_stem.split("_")
            if len(parts) >= 2:
                return datetime.strptime(f"{parts[-2]}_{parts[-1]}", "%Y%m%d_%H%M%S")
        except (IndexError, ValueError):
            return None
        return None

    def clear_video_detections(self) -> None:
        if self.continuous_tracking:
            self._pipeline.clear()
        else:
            self._pipeline.reset()

    def reset_tracker(self) -> None:
        self._pipeline.reset()
