"""Processing contracts for bugcam jobs."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


class StubProcessor:
    """Minimal processor implementation until edge26 is integrated."""

    name = "stub"

    def process(self, media_path: Path, output_dir: Path, job: dict[str, Any]) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        copied_media_path = output_dir / media_path.name
        shutil.copy2(media_path, copied_media_path)

        result = {
            "processor": self.name,
            "job_id": job["job_id"],
            "source_type": job["source_type"],
            "input_media": str(media_path),
            "copied_media": str(copied_media_path),
            "status": "processed",
        }

        result_path = output_dir / "result.json"
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["result_path"] = str(result_path)
        return result


def get_processor() -> StubProcessor:
    """Return the active processor implementation."""
    return StubProcessor()
