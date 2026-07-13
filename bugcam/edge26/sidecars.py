"""Names and semantics of the sidecar files that coordinate a result directory.

A result dir is one terminal unit of pipeline output: a FLIK video chunk
(``<results>/<flick_id>/<YYYYMMDD_HHMMSS...>/``) or a DOT per-track dir
(``<results>/<dot_id>/<YYYYMMDD>/<track>_<HHMMSS>/``). Detection, the
classification worker, the stale sweep, and the publisher hand a dir to each
other through files rather than in-process state, because detection may run in
a separate subprocess and any participant can die and restart between steps.
This module is the single source of truth for those filenames and the rules
each one carries. It covers only the sidecar protocol inside a result dir
(plus the ``.last_recording`` session marker); management of the input,
pending-queue, and output directory trees belongs to their owners elsewhere.

Sidecar files
=============

``results.json`` (RESULTS)
    The payload. Always written via ``results.json.tmp`` (RESULTS_TMP) plus
    atomic rename (ResultsWriter), so readers never see a torn file. Written
    by detection for zero-track dirs, else rewritten by the classification
    worker after each classified track.
``.detection.json`` (DETECTION_META)
    Per-video detection metadata. Written by detection; read by the
    classification worker to enrich results; removed at finalization.
``.expected_tracks`` (EXPECTED_TRACKS)
    Integer count of classification entries detection enqueues for this dir.
    Together with ``.detection.json`` it MUST be on disk before the first
    entry is enqueued: a fast classification otherwise finds no expected
    count, its completion is lost, and the dir waits on the stale sweep.
    Removed at finalization.
``.completed_tracks`` (COMPLETED_TRACKS)
    Integer count of entries resolved so far -- classified, gracefully
    skipped, or permanently failed. Written only by the main-process
    classification worker, exactly one increment per resolved entry. An
    unreadable counter is never reset (that walks the count backwards and the
    dir could then never reach its expected count); the increment is skipped
    and the stale sweep finalizes later. Removed at finalization.
``.done`` (DONE)
    Finalization marker: no further writes land in this dir and it is ready
    to publish. Existence is the signal; the ``key=value`` body is
    informational only. Never removed -- publishing deletes the whole dir.
``.uploaded`` / ``.archived`` / ``.archived-aux`` (LEGACY_UPLOAD_MARKERS)
    Written by a retired upload design. Nothing writes them anymore; they are
    still excluded from publishing so dirs left on disk by old versions do
    not ship stale markers.
``.last_recording`` (LAST_RECORDING)
    Not a result-dir sidecar: lives in input storage and carries the name of
    the last video of a recording session, so the tracker reset at the
    session boundary survives a restart. Owned exclusively by whichever
    process runs the detection loop.

Lifecycle of a result dir
=========================

1. Detection creates the dir and fills the payload (``crops/``,
   ``composites/``, an optional top-level ``video.mp4`` sample).
2. Tracked dirs (>= 1 confirmed track): detection writes ``.detection.json``,
   then ``.expected_tracks``, and only then enqueues the classification
   entries. Zero-track FLIK dirs skip classification entirely: detection
   writes an empty ``results.json``, then ``.done``, then enqueues a publish
   entry (detection may have no upload callback of its own).
3. The classification worker resolves each entry, rewrites ``results.json``
   on success, and increments ``.completed_tracks``.
4. When completed >= expected the worker finalizes: writes ``.done``, removes
   the progress markers (``.expected_tracks``, ``.completed_tracks``,
   ``.detection.json``), and fires the publish callback. A finalized dir
   holding ``.done`` alone is therefore the normal terminal state on disk.
5. Publishing ships every file whose name is not in UPLOAD_EXCLUDE as one
   atomic upload set and deletes the dir; empty results (no tracks, no
   media) are deleted without uploading. Publish does not re-verify
   ``.done`` -- it trusts its caller -- but it requires ``results.json``, so
   a dir finalized without one (possible only when every track resolved
   without a single successful classification) is never shipped or deleted;
   the orphan sweep retries it indefinitely.

Crash recovery: the stale sweep
===============================

Any participant can die between two markers; the sweep re-derives the state
above from markers plus mtimes, on a wall-clock cadence:

- ``.done`` still on disk after the orphan threshold -> the publish callback
  never ran or failed; retry it.
- ``results.json`` present, no ``.expected_tracks``, no ``.done``, past the
  stale threshold -> finalize (``swept=stale``) and publish.
- ``results.json`` and ``.expected_tracks`` both present past the stale
  threshold -> finalize and publish, unless completions are still short of
  expected while queue entries remain (they may yet arrive). A sweep-written
  ``.done`` leaves the progress markers in place, which is fine: publishing
  deletes the dir.
- Neither ``results.json`` nor ``.expected_tracks``, and no file outside
  SWEEP_NON_CONTENT, past the empty threshold -> abandoned; delete the dir.

The startup inventory reads the same markers: ``.done`` means finalized but
never published, ``.expected_tracks`` means awaiting classification.

Process split: with ``detection_in_subprocess`` the child writes the
detection-side files (``.detection.json``, ``.expected_tracks``, zero-track
``results.json``/``.done``) and the parent's classification worker owns
everything after the queue (``.completed_tracks``, finalization, publish).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

RESULTS = "results.json"
RESULTS_TMP = "results.json.tmp"
DETECTION_META = ".detection.json"
EXPECTED_TRACKS = ".expected_tracks"
COMPLETED_TRACKS = ".completed_tracks"
DONE = ".done"
LAST_RECORDING = ".last_recording"
LEGACY_UPLOAD_MARKERS = frozenset({".uploaded", ".archived", ".archived-aux"})

# Two derived sets, distinct on purpose -- they answer different questions.

# Which names must never ship when a finalized dir is published? Includes the
# legacy markers so dirs left by old versions don't upload them; not
# RESULTS_TMP (normally gone via the atomic rename -- a crash leftover would
# ship alongside the payload, harmlessly).
UPLOAD_EXCLUDE = frozenset({DONE, DETECTION_META, EXPECTED_TRACKS, COMPLETED_TRACKS}) | LEGACY_UPLOAD_MARKERS

# Which names do not make an unfinished dir worth keeping? Used by the sweep
# to decide an abandoned dir is empty enough to delete. Includes RESULTS_TMP
# (a torn write is not content); leaves the legacy markers out, so a dir
# holding only those is conservatively kept.
SWEEP_NON_CONTENT = frozenset({DONE, DETECTION_META, EXPECTED_TRACKS, COMPLETED_TRACKS, RESULTS_TMP})


def write_detection_meta(output_dir: Path, meta: dict) -> None:
    (output_dir / DETECTION_META).write_text(json.dumps(meta, indent=2, default=str))


def read_detection_meta(output_dir: Path) -> dict:
    """Detection metadata, or {} when the sidecar is absent or unreadable."""
    meta_path = output_dir / DETECTION_META
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read detection metadata: {e}")
    return {}


def write_expected_tracks(output_dir: Path, count: int) -> None:
    """Record how many classification entries will be enqueued for this dir.

    Contract: call before the first enqueue, or a fast classification finds
    no expected count and the dir never reaches .done on its own."""
    (output_dir / EXPECTED_TRACKS).write_text(str(count))


def has_expected_tracks(output_dir: Path) -> bool:
    return (output_dir / EXPECTED_TRACKS).exists()


def read_expected_tracks(output_dir: Path) -> int | None:
    """The expected count, or None when absent or unreadable."""
    try:
        return int((output_dir / EXPECTED_TRACKS).read_text().strip())
    except (ValueError, OSError):
        return None


def read_completed_tracks(output_dir: Path) -> int | None:
    """The completed count, or None when absent or unreadable."""
    try:
        return int((output_dir / COMPLETED_TRACKS).read_text().strip())
    except (ValueError, OSError):
        return None


def increment_completed_tracks(output_dir: Path) -> int | None:
    """Count one more resolved entry; returns the new count.

    Returns None and leaves the counter untouched when an existing counter is
    unreadable: falling back to 1 would walk the count backwards and the dir
    could then never reach its expected count. Callers defer to the stale
    sweep instead."""
    completed_path = output_dir / COMPLETED_TRACKS
    try:
        completed = int(completed_path.read_text().strip()) + 1
    except FileNotFoundError:
        completed = 1
    except (ValueError, OSError):
        return None
    completed_path.write_text(str(completed))
    return completed


def write_done(output_dir: Path, **fields) -> None:
    """Finalize the dir: no further writes land here, ready to publish.

    Existence of .done is the signal; the key=value body is informational."""
    (output_dir / DONE).write_text("".join(f"{k}={v}\n" for k, v in fields.items()))


def is_done(output_dir: Path) -> bool:
    return (output_dir / DONE).exists()


def clear_progress_markers(output_dir: Path) -> None:
    """Remove the tracking sidecars once a dir is finalized."""
    for name in (EXPECTED_TRACKS, COMPLETED_TRACKS, DETECTION_META):
        (output_dir / name).unlink(missing_ok=True)
