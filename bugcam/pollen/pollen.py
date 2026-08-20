"""Pollen: the device-side upload subsystem.

Owns a SQLite-backed queue, the upload loop, retention, and cleanup. The app enqueues an
artifact (result / heartbeat / log) as it is produced; a background loop uploads
pending items (per-object, or bundled into an archive when batching is on),
marks each success, then deletes the local file and prunes its row.

Lifecycle: ``start()`` runs the loop in a thread; ``flush()`` drains the queue to
empty while still accepting new enqueues; ``stop()`` halts the loop.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from bugcam.pollen.archive import Archiver
from bugcam.pollen.presign import RateLimitError
from bugcam.pollen.staging import StagingArea
from bugcam.pollen.store import PollenStore, UploadRow
from bugcam.pollen.transport import DEFAULT_MULTIPART_THRESHOLD, DEFAULT_PART_SIZE, Uploader
from bugcam.pollen.upload_utils import content_type_for

logger = logging.getLogger("bugcam.pollen")

ARCHIVE_KIND = "archive"
# Kinds that are uploaded individually even in batch mode: large, un-indexed artifacts
# (videos) would otherwise push a per-device tar past the multipart threshold and trap
# the small result data inside a slow/stuck multipart upload.
UNBATCHED_KINDS = frozenset({"video"})
# Latency-sensitive telemetry: tiny objects that ship individually, before
# everything else in a tick, and never inside an archive -- a heartbeat trapped
# behind the batch cadence defeats its purpose.
PRIORITY_KINDS = frozenset({"heartbeat"})
MAX_RETRY_DELAY_SECONDS = 300  # matches the legacy upload loop
STUCK_WARN_SECONDS = 3600      # warn loudly once the oldest item has waited this long


def _exists_safe(path: Path) -> Optional[bool]:
    """Like Path.exists(), but doesn't let an ambiguous OSError pass through.
    Path.exists() already swallows ENOENT/ENOTDIR/ELOOP and returns False; it
    re-raises anything else (e.g. ESTALE on a disconnected mount, EACCES on a
    dead automount stub). Callers checking a path recorded on a mount that may
    no longer exist need to tell "confirmed gone" (False) apart from "couldn't
    tell" (None) rather than crash on the latter."""
    try:
        return path.exists()
    except OSError:
        return None


@dataclass(frozen=True)
class KindPolicy:
    """Per-kind retention. ``keep_after_upload`` retains a local copy (in retained/) plus
    a dedup tombstone after upload; otherwise the staged copy and the row are dropped."""
    keep_after_upload: bool = False


@dataclass
class PollenConfig:
    db_path: Path
    output_root: Path
    staging_dir: Path
    key_prefix: str = "v1"
    poll_interval: float = 10.0
    multipart_threshold: int = DEFAULT_MULTIPART_THRESHOLD
    part_size: int = DEFAULT_PART_SIZE
    batch: bool = False
    videos_per_tick: int = 10  # max un-batched videos per tick, so a backlog can't starve archives
    delete_after_upload: bool = True
    retain_uploaded: bool = False  # keep a local copy (in retained/) after upload
    retention_by_kind: dict[str, KindPolicy] = field(default_factory=dict)  # per-kind override
    reconcile_grace_seconds: float = 300.0  # min age before an unreferenced staged link is swept


class Pollen:
    def __init__(
        self,
        config: PollenConfig,
        *,
        presigner: Any = None,
        uploader: Any = None,
        archiver: Optional[Archiver] = None,
        store: Optional[PollenStore] = None,
        clock: Optional[Callable[[], datetime]] = None,
        enqueue_source: Optional[Callable[["Pollen"], None]] = None,
    ) -> None:
        self.config = config
        self.store = store or PollenStore(config.db_path)
        self._staging = StagingArea([config.output_root])
        self.uploader = uploader or Uploader(
            presigner, self.store,
            multipart_threshold=config.multipart_threshold,
            part_size=config.part_size,
        )
        self.archiver = archiver
        self._clock = clock or datetime.now
        self._source = enqueue_source  # called each tick to enqueue ready outputs
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    # enqueue
    # ------------------------------------------------------------------ #
    def enqueue_set(self, files: list[str | Path], *, device: str, kind: str) -> list[int]:
        """Queue a logical set atomically: stage every file, then insert all rows in one
        transaction so claim/archive never splits the set. ``device`` is the batch group
        (stored explicitly, not parsed from the key). The producer owns its files and
        should delete them after this returns. Returns the row ids enqueued.

        Note: if staging (hardlink) raises partway through the loop, this propagates to
        the caller and NOTHING from this set is enqueued -- files already staged before
        the failure become orphaned links, and the producer keeps its originals (since
        it deletes them only after this call returns). Callers must not swallow the
        exception silently; see Pipeline._notify_result_ready / _notify_video_ready."""
        specs: list[dict] = []
        missing = 0
        deduped = 0
        for path in files:
            path = Path(path)
            if not path.exists():
                missing += 1
                continue
            s3_key = self._derive_key(path)
            if self.store.has_key(s3_key):
                deduped += 1
                continue  # already queued/shipped -> skip before staging (no churn)
            size = path.stat().st_size
            staged = self._staging.link(path)
            specs.append({
                "staging_path": str(staged), "kind": kind, "s3_key": s3_key,
                "producer_name": str(path), "metadata": {"device": device}, "size": size,
            })
        if missing or deduped:
            logger.info(
                "enqueue_set(device=%s, kind=%s): %d of %d file(s) skipped (missing=%d, already-queued=%d)",
                device, kind, missing + deduped, len(files), missing, deduped,
            )
        ids = self.store.enqueue_many(specs)
        if len(ids) < len(specs):
            logger.warning(
                "enqueue_set(device=%s, kind=%s): %d staged file(s) failed to insert "
                "(s3_key collision at insert time) -- their staged copies are now orphaned",
                device, kind, len(specs) - len(ids),
            )
        return ids

    def _derive_key(self, path: Path) -> str:
        root = self.config.output_root.resolve()
        resolved = Path(path).resolve()
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            rel = Path(resolved.name)
        return f"{self.config.key_prefix}/{rel.as_posix()}"

    def upload_now(self, data: bytes, s3_key: str, content_type: str) -> None:
        """Upload in-memory bytes to a fixed key immediately, bypassing the queue.

        For fixed-key objects the durable queue does not own (e.g. the manifest)."""
        self.uploader.upload_bytes(s3_key, data, content_type)

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="Pollen", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def upload_stats(self, now: Optional[datetime] = None) -> dict:
        """Queue health for observability: how many are pending, how long the
        oldest has waited, and the worst attempt count."""
        summary = self.store.pending_summary()
        oldest_age = None
        if summary["oldest_created_at"]:
            oldest = datetime.fromisoformat(summary["oldest_created_at"])
            oldest_age = ((now or datetime.now(timezone.utc)) - oldest).total_seconds()
        return {
            "pending": summary["pending"],
            "pending_bytes": summary["pending_bytes"],
            "oldest_age_seconds": oldest_age,
            "max_attempts": summary["max_attempts"],
        }

    def stats(self, now: Optional[datetime] = None) -> dict:
        """Upload health for the heartbeat: the pending backlog plus the bandwidth
        window since the last call (drained -- the heartbeat is the sole consumer)."""
        stats = self.upload_stats(now)
        transfer = getattr(self.uploader, "transfer_stats", None)
        if transfer is not None:
            stats.update(transfer.drain())
        return stats

    def upload_path_now(self, path: Path | str) -> None:
        """Immediate presigned PUT of a small producer file at its derived key,
        bypassing the queue. For latency-sensitive telemetry (heartbeats); callers
        fall back to ``enqueue_set`` on failure for durability."""
        path = Path(path)
        self.uploader.upload_bytes(
            self._derive_key(path), path.read_bytes(), content_type_for(path.name)
        )

    def _warn_if_stuck(self) -> None:
        stats = self.upload_stats()
        age = stats["oldest_age_seconds"]
        if age is not None and age >= STUCK_WARN_SECONDS:
            logger.error(
                "pollen: %d upload(s) stuck — oldest pending %.0fs over %d attempts; "
                "data is retained but not reaching S3",
                stats["pending"], age, stats["max_attempts"],
            )

    def flush(self) -> None:
        """Drain the queue, still accepting enqueues. Returns when empty or when a
        tick makes no progress (uploads failing) so it never spins forever."""
        while not self._stop.is_set():
            before = self.store.pending_count()
            if before == 0:
                return
            try:
                self._tick()
            except RateLimitError:
                return  # backend throttling; leave the rest durable for next run
            if self.store.pending_count() >= before:
                return  # no progress this pass; don't hang the shutdown

    def reconcile(self) -> None:
        """Crash-recovery GC. Drop pending rows whose staged copy vanished (a lost
        upload), prune shipped rows whose file is gone, and unlink staged files no
        row references (orphaned by a crash between link and enqueue).

        A row's staging_path is whatever mount was current when it was enqueued;
        redirecting to a new drive leaves old rows pointing at a mount that may no
        longer be there at all. ``_exists_safe`` tells a confirmed-gone path (drop
        it) apart from an unreachable one (stale/disconnected mount raising
        something Path.exists() doesn't swallow) -- the latter is left alone rather
        than guessed at."""
        for row in self.store.claim_pending():
            exists = _exists_safe(Path(row.staging_path))
            if exists is False:
                logger.error(
                    "pollen: staged file gone for pending %s; dropping (lost upload)", row.s3_key
                )
                self.store.delete(row.id)
            elif exists is None:
                logger.warning(
                    "pollen: could not check staged file for pending %s (mount unavailable?); "
                    "leaving pending", row.s3_key
                )
        self.store.prune_missing()
        known = self.store.all_staging_paths()
        now = time.time()
        for link in self._staging.iter_links():
            if str(link) in known:
                continue
            try:
                age = now - link.stat().st_mtime
            except OSError:
                continue
            if age >= self.config.reconcile_grace_seconds:
                self._staging.unlink(link)

    def _loop(self) -> None:
        try:
            self.reconcile()  # recover orphans/lost uploads left by a previous run
        except Exception:
            # An uncaught exception here would kill this thread before the tick
            # loop's own try/except ever runs -- and since it's a thread exception,
            # not a logging call, it goes to stderr via threading.excepthook and
            # never reaches the log file. Log it through the normal pipeline and
            # keep going: a failed startup reconcile is recoverable, a dead loop is not.
            logger.exception("pollen: startup reconcile failed; continuing without it")
        consecutive_failures = 0
        while not self._stop.is_set():
            try:
                tick_failures = self._tick()
            except RateLimitError as exc:
                consecutive_failures += 1
                delay = exc.retry_after or min(self.config.poll_interval * 2, MAX_RETRY_DELAY_SECONDS)
                logger.warning("pollen rate limited; backing off %ss", delay)
                self._stop.wait(delay)
                continue
            except Exception:
                consecutive_failures += 1
                delay = min(self.config.poll_interval * (2 ** consecutive_failures), MAX_RETRY_DELAY_SECONDS)
                logger.exception("pollen tick failed; backing off %ss", delay)
                self._stop.wait(delay)
                continue
            if tick_failures:
                consecutive_failures += 1
                delay = min(self.config.poll_interval * (2 ** consecutive_failures), MAX_RETRY_DELAY_SECONDS)
                logger.warning("pollen: %d upload(s) failed; backing off %ss", tick_failures, delay)
                self._warn_if_stuck()
                self._stop.wait(delay)
            else:
                consecutive_failures = 0
                self._stop.wait(self.config.poll_interval)

    # ------------------------------------------------------------------ #
    # the work
    # ------------------------------------------------------------------ #
    def _tick(self) -> int:
        """Run one upload pass. Returns the number of failed uploads; raises
        RateLimitError so the loop can honour backend backoff."""
        if self._source is not None:
            try:
                self._source(self)  # enqueue any ready outputs (results, logs, ...)
            except Exception:
                logger.exception("pollen enqueue source failed")
        pending = self.store.claim_pending()
        failures = 0
        try:
            if self.config.batch and self.archiver is not None:
                failures = self._upload_batched(pending)
            else:
                # Priority kinds (heartbeats) first so telemetry never waits
                # behind a slow video PUT within the tick.
                for row in sorted(pending, key=lambda r: r.kind not in PRIORITY_KINDS):
                    if self._drop_if_lost(row):
                        continue
                    if not self._upload_one(row):
                        failures += 1
        except Exception as exc:
            logger.warning("tick aborted (%s: %s); running cleanup anyway", type(exc).__name__, exc)
            raise
        finally:
            # Cleanup only touches UPLOADED rows, so it is safe (and necessary)
            # even when the upload leg aborted mid-tick.
            cleaned, retained = self._cleanup()
            logger.info(
                "tick summary: uploaded=%d failed=%d cleaned=%d retained=%d pending=%d",
                cleaned + retained, failures, cleaned, retained, self.store.pending_count(),
            )
        return failures

    def _upload_one(self, row: UploadRow) -> bool:
        """Upload one row. True on success; False on a per-file error (left pending,
        not deleted). RateLimitError propagates so the whole loop backs off."""
        size = f"{row.size / 1e6:.1f} MB" if row.size else "size unknown"
        logger.info("uploading %s (kind=%s, %s, attempt %d)", row.s3_key, row.kind, size, row.attempts + 1)
        try:
            self.store.record_attempt(row.id)
            started = time.monotonic()
            self.uploader.upload(row)
            elapsed = time.monotonic() - started
            self.store.mark_uploaded(row.id)
            if row.size and elapsed > 0:
                logger.info("uploaded %s (kind=%s, %.1f MB in %.1fs, %.2f MB/s)",
                            row.s3_key, row.kind, row.size / 1e6, elapsed, row.size / 1e6 / elapsed)
            else:
                logger.info("uploaded %s (kind=%s, %.1fs)", row.s3_key, row.kind, elapsed)
            return True
        except RateLimitError:
            raise
        except Exception as exc:
            # Transient (timeouts, connection resets) and self-retried -- one line, no
            # traceback; the file is kept and the row stays pending.
            logger.warning(
                "upload failed %s (kind=%s, attempt %d, file kept, will retry): %s: %s",
                row.s3_key, row.kind, row.attempts + 1, type(exc).__name__, exc,
            )
            return False

    def _upload_batched(self, pending: list[UploadRow]) -> int:
        # Archive rows already in flight (e.g. from a previous failed tick) retry
        # directly; their members ride them, so they are excluded from re-packing.
        # A tar whose staged file is lost is dropped WITHOUT reserving: its members
        # become free to re-pack into a fresh tar this same tick.
        failures = 0
        # Priority kinds (heartbeats) ship individually FIRST: they are tiny,
        # latency-sensitive, and must never wait on packing or a slow video PUT.
        for row in (r for r in pending if r.kind in PRIORITY_KINDS):
            if self._drop_if_lost(row):
                continue
            if not self._upload_one(row):
                failures += 1
        reserved: set[int] = set()
        for row in (r for r in pending if r.kind == ARCHIVE_KIND):
            if self._drop_if_lost(row):
                continue
            reserved.update(row.metadata.get("members", []))
            if not self._upload_archive_row(row):
                failures += 1
        members = [
            r for r in pending
            if r.kind != ARCHIVE_KIND and r.kind not in PRIORITY_KINDS and r.id not in reserved
        ]
        # Batch and ship the result archives FIRST (small, indexed) -- the large
        # un-batched videos go last (below) so results never wait behind a slow video PUT.
        by_device: dict[str, list[UploadRow]] = defaultdict(list)
        for row in (r for r in members if r.kind not in UNBATCHED_KINDS):
            if self._drop_if_lost(row):  # a lost member must not crash pack()
                continue
            by_device[self._device_of(row)].append(row)

        timestamp = self._clock().strftime("%Y%m%d_%H%M%S")
        for device, items in by_device.items():
            s3_key = self.archiver.key_for(device, timestamp)
            if self.store.has_key(s3_key):
                # Same key as a queued tar (fixed timestamp within one poll): packing
                # would overwrite its staged file. Members wait for the next tick.
                logger.info("archive %s already queued; %d member(s) wait for the next tick",
                            s3_key, len(items))
                continue
            try:
                artifact = self.archiver.pack(device, items, self.config.staging_dir, timestamp=timestamp)
            except Exception as exc:  # one device's bad pack must not wedge the queue
                logger.warning("packing archive for device %s failed (will retry): %s: %s",
                               device, type(exc).__name__, exc)
                failures += 1
                continue
            if artifact is None:
                logger.info("nothing to pack for device %s", device)
                continue
            tar_id = self.store.enqueue(
                str(artifact.path), kind=ARCHIVE_KIND, s3_key=artifact.s3_key,
                metadata={"members": [item.id for item in items]},
            )
            if tar_id is None:
                logger.info("archive %s already queued; skipping re-enqueue", artifact.s3_key)
                continue
            if self._upload_archive_row(self.store.get(tar_id)):
                logger.info("uploaded archive %s (%d members, device=%s)",
                            artifact.s3_key, len(items), device)
            else:
                failures += 1

        # Un-batched kinds (videos) ship individually and LAST, capped per tick so a
        # backlog cannot starve archive retries or delay cleanup for hours. Attempts-
        # first ordering keeps one failing video from monopolising the capped lane.
        def _video_order(r: UploadRow) -> tuple[int, int]:
            return (r.attempts, r.id)
        videos = sorted(
            (r for r in members if r.kind in UNBATCHED_KINDS),
            key=_video_order,
        )
        deferred = len(videos) - min(len(videos), self.config.videos_per_tick)
        if deferred:
            # The cap otherwise makes a growing backlog invisible: pending_count()
            # keeps climbing but nothing in a per-tick log says why videos aren't
            # draining -- one waits per tick regardless of how many pile up behind it.
            logger.info(
                "%d video(s) waiting behind the %d-per-tick cap (oldest: %s, %d attempt(s))",
                deferred, self.config.videos_per_tick, videos[0].s3_key, videos[0].attempts,
            )
        for row in videos[: self.config.videos_per_tick]:
            if self._drop_if_lost(row):
                continue
            if not self._upload_one(row):
                failures += 1
        return failures

    def _drop_if_lost(self, row: UploadRow) -> bool:
        """A pending row whose staged copy vanished can never upload; drop it (the
        startup reconcile rule, applied mid-run) instead of retrying forever."""
        if Path(row.staging_path).exists():
            return False
        logger.error("staged file gone for %s (kind=%s); dropping row (lost upload)",
                     row.s3_key, row.kind)
        self.store.delete(row.id)
        return True

    def _upload_archive_row(self, row: UploadRow) -> bool:
        """Upload a tar row; on success its members shipped inside it, so mark them."""
        if not self._upload_one(row):
            return False
        for member_id in row.metadata.get("members", []):
            self.store.mark_uploaded(member_id)
        return True

    def _device_of(self, row: UploadRow) -> str:
        # Device is passed explicitly at enqueue and stored on the row.
        return row.metadata["device"]

    def _policy_for(self, kind: str) -> KindPolicy:
        """Resolve the retention policy for a kind: explicit per-kind override, else the
        default derived from the global delete_after_upload / retain_uploaded knobs."""
        policy = self.config.retention_by_kind.get(kind)
        if policy is not None:
            return policy
        keep = (not self.config.delete_after_upload) or self.config.retain_uploaded
        return KindPolicy(keep_after_upload=keep)

    def _cleanup(self) -> tuple[int, int]:
        # Retention is decided per kind, by the spooler -- not the producer. keep_after_upload
        # retains a local copy (retained/) plus a dedup tombstone; otherwise the staged copy
        # and row are dropped. The producer owns and deletes its own originals either way.
        cleaned = retained = 0
        for row in self.store.uploaded_rows():
            staged = Path(row.staging_path)
            if self._policy_for(row.kind).keep_after_upload:
                self._staging.retain(staged)
                self.store.mark_done(row.id)  # tombstone dedups re-enqueues of the same key
                retained += 1
                logger.info("retained %s (staged copy moved to retained/; keep_after_upload)", row.s3_key)
            else:
                self._staging.unlink(staged)
                self.store.delete(row.id)
                cleaned += 1
                logger.info("cleaned %s (staged copy deleted; delete_after_upload)", row.s3_key)
        return cleaned, retained
