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
pending-queue, and output directory trees belongs to their owners elsewhere
(e.g. the utility subdirs in ``main.NON_RESULT_SUBDIRS`` that the sweep and
inventory must skip).

Sidecar files
=============

``results.json`` (RESULTS)
    The payload. Always written via ``results.json.tmp`` (RESULTS_TMP) plus
    atomic rename (ResultsWriter), so readers never see a torn file. Written
    by detection for zero-track dirs, else rewritten by the classification
    worker after each classified track.
``.detection.json`` (DETECTION_META)
    Per-video detection metadata, FLIK dirs only (DOT per-track dirs carry
    their metadata in the queue entry and labels file instead). Written by
    detection; read by the classification worker to enrich results; removed
    at finalization.
``.expected_tracks`` (EXPECTED_TRACKS)
    Integer count of classification entries detection enqueues for this dir
    (always ``1`` for a DOT per-track dir). It MUST be on disk before the
    first entry is enqueued: a fast classification otherwise finds no
    expected count, its completion is lost, and the dir waits on the stale
    sweep. Removed at finalization.
``.completed_tracks`` (COMPLETED_TRACKS)
    Integer count of entries resolved so far -- classified, gracefully
    skipped, or permanently failed. Written only by the main-process
    classification worker, exactly one increment per resolved entry. An
    unreadable counter is never reset (that walks the count backwards and the
    dir could then never reach its expected count); the increment is skipped
    and the stale sweep finalizes later. Removed at finalization.
``.done`` (DONE)
    Finalization marker: no further writes land in this dir and it is ready
    to publish. Existence is the only control-flow signal. The ``key=value``
    body (``classified=``/``completed=``/``expected=``, or ``swept=stale``
    when the sweep force-finalized) is diagnostic: the result-health audit
    parses it to flag sweep-finalized or double-counted dirs in the logs,
    but nothing branches on it. Never removed -- publishing deletes the
    whole dir.
``.uploaded`` / ``.archived`` / ``.archived-aux`` (LEGACY_UPLOAD_MARKERS)
    Written by a retired upload design. Nothing writes them anymore; they are
    still excluded from publishing so dirs left on disk by old versions do
    not ship stale markers.
``.last_recording`` (LAST_RECORDING)
    Not a result-dir sidecar: lives in input storage and carries the name of
    the last video of a recording session, so the tracker reset at the
    session boundary survives a restart. Written by the recorder owner (the
    parent process) when recording stops; loaded at startup and cleared
    after the boundary video only by whichever instance runs the detection
    loop -- in subprocess mode the parent must not consume it out from under
    the child.

Lifecycle of a result dir
=========================

1. Detection creates the dir and fills the payload (``crops/``,
   ``composites/``, an optional top-level ``video.mp4`` sample).
2. Tracked dirs (>= 1 confirmed track): detection writes ``.detection.json``
   (FLIK only), then ``.expected_tracks``, and only then enqueues the
   classification entries. Zero-track FLIK dirs skip classification
   entirely: detection writes an empty ``results.json``, then ``.done``,
   then enqueues an ``entry_type="result"`` publish entry -- detection may
   have no upload callback of its own, so the main-process worker must do
   the publishing, and zero-track dirs have no track entries that would
   otherwise trigger it.
3. The classification worker resolves each entry, rewrites ``results.json``
   on success, and increments ``.completed_tracks``.
4. When completed >= expected the worker finalizes: writes ``.done``,
   removes the progress markers (``.expected_tracks``, ``.completed_tracks``,
   ``.detection.json``), runs the result-health audit (result_health --
   pure inspection, one error line if the dir looks unhealthy), and fires
   the publish callback. A finalized dir holding ``.done`` alone is
   therefore the normal terminal state on disk.
5. Publishing (result_publish) ships every file whose name is not in
   UPLOAD_EXCLUDE as one atomic upload set and deletes the dir; empty
   results (no tracks, no crop/composite/video media) are deleted without
   uploading. Publish does not re-verify ``.done`` -- it trusts its caller
   -- but it requires ``results.json`` and an owning device resolvable from
   the dir path, so a dir missing either (no ``results.json`` is possible
   only when every track resolved without a single successful
   classification) is never shipped or deleted; the orphan sweep retries it
   indefinitely, logging an error each pass.

Crash recovery: the stale sweep
===============================

Any participant can die between two markers; the sweep (run from the
classification worker on a wall-clock cadence, since in subprocess mode only
that worker holds the upload callback) re-derives the state above from
markers plus mtimes:

- ``.done`` still on disk after the orphan threshold -> the publish callback
  never ran or failed; retry it.
- ``results.json`` present, no ``.expected_tracks``, no ``.done``, past the
  stale threshold -> finalize (``swept=stale``), audit, and publish.
- ``results.json`` and ``.expected_tracks`` both present past the stale
  threshold -> finalize, audit, and publish, unless completions are still
  short of expected while queue entries remain (they may yet arrive). A
  sweep-written ``.done`` leaves the progress markers in place, which is
  fine: publishing deletes the dir.
- Neither ``results.json`` nor ``.expected_tracks``, and no file outside
  SWEEP_NON_CONTENT, past the empty threshold -> abandoned; delete the dir.

The startup inventory reads the same markers: ``.done`` means finalized but
never published, ``.expected_tracks`` means awaiting classification.

Process split: with ``detection_in_subprocess`` the child writes the
detection-side files (``.detection.json``, ``.expected_tracks``, zero-track
``results.json``/``.done``) and the parent's classification worker owns
everything after the queue (``.completed_tracks``, finalization, audit,
publish).
"""
from __future__ import annotations

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
