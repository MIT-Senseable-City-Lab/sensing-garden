"""Produce-site result enqueue + per-tick log enqueue.

Results are enqueued at their produce site (the pipeline's on-result-ready hook ->
``enqueue_result_dir``), which also deletes the finalized FLIK dir once enqueued --
Pollen holds a staged hardlink, so the producer owns its own cleanup. Logs have no
produce-site event (a per-day file appended all day), so a completed prior-day log
is discovered by scanning; the tombstone dedups re-scans of the same key.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from bugcam.pollen.upload_utils import result_is_empty

RESULTS_FILENAME = "results.json"
SIDECARS = {
    ".done", ".detection.json", ".expected_tracks", ".completed_tracks",
    ".uploaded", ".archived", ".archived-aux",
}


def enqueue_ready_outputs(pollen, output_dir, flick_id: str, dot_ids: list[str], *, today: str | None = None) -> int:
    """Per-tick: prune tombstones, enqueue completed logs."""
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return 0
    pollen.store.prune_missing()  # bound tombstones whose files are gone
    return _enqueue_logs(pollen, output_dir, today=today)


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


def _enqueue_logs(pollen, output_dir: Path, *, today: str | None = None) -> int:
    today = today or datetime.now().strftime("%Y%m%d")
    count = 0
    for log_dir in sorted(output_dir.glob("*/logs")):
        if not log_dir.is_dir():
            continue
        for path in sorted(p for p in log_dir.iterdir() if p.is_file()):
            if path.name.startswith("."):
                continue
            if today in path.name:
                continue  # current day's log is still being appended; ship after rollover
            if pollen.enqueue(path, "log", retain=True) is not None:
                count += 1
    return count
