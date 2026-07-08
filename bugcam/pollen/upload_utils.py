"""Shared helpers producers lean on when deciding how to upload an artifact.

Producers decide *what* to enqueue; these are the bits they share: the content type
for a filename, and whether a result has anything worth shipping.
"""
from __future__ import annotations

import json
from pathlib import Path

JSON = "application/json"


def content_type_for(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".mp4"):
        return "video/mp4"
    if lowered.endswith(".json"):
        return JSON
    if lowered.endswith((".log", ".txt")):
        return "text/plain"
    if lowered.endswith(".tar"):
        return "application/x-tar"
    return "application/octet-stream"


def result_is_empty(results_json: Path) -> bool:
    """True when a result has zero tracks and no crop/composite/video media."""
    results_json = Path(results_json)
    try:
        payload = json.loads(results_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("tracks"):
        return False
    results_dir = results_json.parent
    for sub in ("crops", "composites", "videos"):
        media_dir = results_dir / sub
        if media_dir.is_dir() and any(p.is_file() for p in media_dir.rglob("*")):
            return False
    # The FLIK video sample lands top-level (video.mp4), not under videos/;
    # a zero-track dir holding one is exactly the backdrop footage case.
    if any(p.is_file() and p.suffix == ".mp4" for p in results_dir.iterdir()):
        return False
    return True
