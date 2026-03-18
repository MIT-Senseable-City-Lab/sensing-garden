"""Vendored results writer from edge26."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


class ResultsWriter:
    """Write edge26-compatible result payloads to disk."""

    def __init__(self, results_dir: Path):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def write_results(self, results: Dict, output_dir: Path) -> Dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "results.json"
        json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        logger.info("Results saved: %s", json_path)
        return {"json": json_path}

    def write_summary(self, all_results: List[Dict]) -> Path:
        total_confirmed = 0
        total_tracks = 0
        species_counts: dict[str, int] = {}

        for result in all_results:
            summary = result.get("summary", {})
            total_confirmed += summary.get("confirmed_tracks", 0)
            total_tracks += summary.get("total_tracks", 0)
            for track in result.get("tracks", []):
                species = track.get("final_prediction", {}).get("species", "Unknown")
                species_counts[species] = species_counts.get(species, 0) + 1

        summary_path = self.results_dir / "processing_summary.json"
        summary_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now().isoformat(),
                    "total_videos": len(all_results),
                    "total_tracks": total_tracks,
                    "total_confirmed": total_confirmed,
                    "species_counts": species_counts,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return summary_path
