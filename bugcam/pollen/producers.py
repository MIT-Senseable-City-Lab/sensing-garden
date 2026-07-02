"""Produce-site result enqueue.

Results are enqueued at their produce site (the pipeline's on-result-ready hook ->
``enqueue_result_dir``), which also deletes the finalized FLIK dir once enqueued --
Pollen holds a staged hardlink, so the producer owns its own cleanup. Logs are pushed
by the logging mechanism on rollover (see ``bugcam.log_shipping``); Pollen never scans.
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


def enqueue_result_dir(pollen, results_dir, flick_id: str, dot_ids: list[str]) -> int:
    """Enqueue one finalized result dir's files (produce-site hook). The FLIK dir is
    deleted once enqueued (Pollen holds staged hardlinks); DOT dirs are retained."""
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
    count = 0
    for path in sorted(results_dir.rglob("*")):
        if path.is_file() and path.name not in SIDECARS:
            if pollen.enqueue(path, "result", retain=is_dot) is not None:
                count += 1
    if is_flik:
        shutil.rmtree(results_dir, ignore_errors=True)  # enqueued -> staged; producer is done
    return count
