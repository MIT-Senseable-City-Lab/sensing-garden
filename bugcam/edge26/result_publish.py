"""Produce-site publishing of a finalized result dir to the upload subsystem.

Lives on the produce side (edge26), not in the upload subsystem: it discovers the
finalized dir's files, decides emptiness, and hands the complete set to the spooler
with the owning device via ``enqueue_set`` (atomic, so the set never splits across
archives), then deletes its own dir. The spooler does no scanning or classification.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from bugcam.pollen.upload_utils import result_is_empty

RESULTS_FILENAME = "results.json"
SIDECARS = {
    ".done", ".detection.json", ".expected_tracks", ".completed_tracks",
    ".uploaded", ".archived", ".archived-aux",
}


def publish_result_dir(pollen, results_dir, flick_id: str, dot_ids: list[str]) -> int:
    """Enqueue one finalized result dir's files as a single set, then clean up. The FLIK
    dir is deleted once enqueued (the spooler holds staged hardlinks)."""
    results_dir = Path(results_dir)
    results_json = results_dir / RESULTS_FILENAME
    if not results_json.exists():
        return 0
    device = results_dir.parent.name
    is_flik = device == flick_id
    is_dot = device in dot_ids
    if not (is_flik or is_dot):
        return 0
    if result_is_empty(results_json):
        if is_flik:
            shutil.rmtree(results_dir, ignore_errors=True)  # nothing detected: junk
        return 0
    files = [p for p in sorted(results_dir.rglob("*")) if p.is_file() and p.name not in SIDECARS]
    ids = pollen.enqueue_set(files, device=device, kind="result")
    if is_flik:
        shutil.rmtree(results_dir, ignore_errors=True)  # enqueued -> staged; producer is done
    return len(ids)
