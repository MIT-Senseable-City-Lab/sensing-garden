"""Produce-site publishing of a finalized result dir to the upload subsystem.

Lives on the produce side (edge26), not in the upload subsystem: it discovers the
finalized dir's files, decides emptiness, and hands the complete set to the spooler
with the owning device via ``enqueue_set`` (atomic, so the set never splits across
archives), then deletes its own dir. The spooler does no scanning or classification.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from bugcam.pollen.upload_utils import result_is_empty

logger = logging.getLogger(__name__)

RESULTS_FILENAME = "results.json"
SIDECARS = {
    ".done", ".detection.json", ".expected_tracks", ".completed_tracks",
    ".uploaded", ".archived", ".archived-aux",
}


def _owning_device(results_dir: Path, flick_id: str, dot_ids: list[str]):
    """Resolve the device that owns a finalized result dir from its path.

    A FLIK chunk sits one level under the device (``<flick>/<chunk_ts>/``); a DOT
    per-track dir sits under the date (``<dot>/<YYYYMMDD>/<track>/``). So the device
    is the dir's parent (FLIK) or grandparent (DOT). Returns (device, is_flik, is_dot)."""
    for seg in (results_dir.parent.name, results_dir.parent.parent.name):
        if seg == flick_id:
            return seg, True, False
        if seg in dot_ids:
            return seg, False, True
    return None, False, False


def publish_result_dir(pollen, results_dir, flick_id: str, dot_ids: list[str]) -> int:
    """Enqueue one finalized result dir's files as a single set, then delete the dir.
    Both FLIK chunks and DOT per-track dirs are terminal units: uploaded once and
    removed (the spooler holds staged hardlinks)."""
    results_dir = Path(results_dir)
    results_json = results_dir / RESULTS_FILENAME
    if not results_json.exists():
        return 0
    device, is_flik, is_dot = _owning_device(results_dir, flick_id, dot_ids)
    if not (is_flik or is_dot):
        return 0
    if result_is_empty(results_json):
        shutil.rmtree(results_dir, ignore_errors=True)  # nothing to ship: terminal, drop it
        logger.info("result %s empty -> dropped, nothing uploaded", results_dir.name)
        return 0
    files = [p for p in sorted(results_dir.rglob("*")) if p.is_file() and p.name not in SIDECARS]
    video_count = sum(1 for p in files if p.suffix == ".mp4")
    try:
        total_mb = sum(p.stat().st_size for p in files) / 1e6
    except OSError:
        total_mb = -1.0
    ids = pollen.enqueue_set(files, device=device, kind="result")
    shutil.rmtree(results_dir, ignore_errors=True)  # enqueued -> staged; producer is done
    logger.info(
        "published %s: %d files, %d video(s), %.1f MB (device=%s, %s) -> enqueued; local dir removed",
        results_dir.name, len(ids), video_count, total_mb, device, "flik" if is_flik else "dot",
    )
    return len(ids)
