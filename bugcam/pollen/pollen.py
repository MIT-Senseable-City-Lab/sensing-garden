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

logger = logging.getLogger("bugcam.pollen")

ARCHIVE_KIND = "archive"
MAX_RETRY_DELAY_SECONDS = 300  # matches the legacy upload loop
STUCK_WARN_SECONDS = 3600      # warn loudly once the oldest item has waited this long


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
        should delete them after this returns. Returns the row ids enqueued."""
        specs: list[dict] = []
        for path in files:
            path = Path(path)
            if not path.exists():
                continue
            s3_key = self._derive_key(path)
            if self.store.has_key(s3_key):
                continue  # already queued/shipped -> skip before staging (no churn)
            size = path.stat().st_size
            staged = self._staging.link(path)
            specs.append({
                "staging_path": str(staged), "kind": kind, "s3_key": s3_key,
                "producer_name": str(path), "metadata": {"device": device}, "size": size,
            })
        return self.store.enqueue_many(specs)

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
            "oldest_age_seconds": oldest_age,
            "max_attempts": summary["max_attempts"],
        }

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
        row references (orphaned by a crash between link and enqueue)."""
        for row in self.store.claim_pending():
            if not Path(row.staging_path).exists():
                logger.error(
                    "pollen: staged file gone for pending %s; dropping (lost upload)", row.s3_key
                )
                self.store.delete(row.id)
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
        self.reconcile()  # recover orphans/lost uploads left by a previous run
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
        if self.config.batch and self.archiver is not None:
            failures = self._upload_batched(pending)
        else:
            failures = sum(0 if self._upload_one(row) else 1 for row in pending)
        self._cleanup()
        return failures

    def _upload_one(self, row: UploadRow) -> bool:
        """Upload one row. True on success; False on a per-file error (left pending,
        not deleted). RateLimitError propagates so the whole loop backs off."""
        try:
            self.store.record_attempt(row.id)
            self.uploader.upload(row)
            self.store.mark_uploaded(row.id)
            return True
        except RateLimitError:
            raise
        except Exception:
            logger.exception("upload failed for %s (will retry; file kept)", row.s3_key)
            return False

    def _upload_batched(self, pending: list[UploadRow]) -> int:
        # Archive rows already in flight (e.g. from a previous interrupted tick)
        # upload directly; the rest are bundled per device.
        failures = 0
        for row in (r for r in pending if r.kind == ARCHIVE_KIND):
            if not self._upload_one(row):
                failures += 1
        members = [r for r in pending if r.kind != ARCHIVE_KIND]
        if not members:
            return failures

        by_device: dict[str, list[UploadRow]] = defaultdict(list)
        for row in members:
            by_device[self._device_of(row)].append(row)

        timestamp = self._clock().strftime("%Y%m%d_%H%M%S")
        for device, items in by_device.items():
            artifact = self.archiver.pack(device, items, self.config.staging_dir, timestamp=timestamp)
            if artifact is None:
                continue
            tar_id = self.store.enqueue(str(artifact.path), kind=ARCHIVE_KIND, s3_key=artifact.s3_key)
            if tar_id is None:
                continue  # archive key already queued (same timestamp); try next tick
            try:
                self.store.record_attempt(tar_id)
                self.uploader.upload(self.store.get(tar_id))
                self.store.mark_uploaded(tar_id)
                for item in items:
                    self.store.mark_uploaded(item.id)
            except RateLimitError:
                raise
            except Exception:
                logger.exception("archive upload failed for %s (will retry)", artifact.s3_key)
                failures += 1
        return failures

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

    def _cleanup(self) -> None:
        # Retention is decided per kind, by the spooler -- not the producer. keep_after_upload
        # retains a local copy (retained/) plus a dedup tombstone; otherwise the staged copy
        # and row are dropped. The producer owns and deletes its own originals either way.
        for row in self.store.uploaded_rows():
            staged = Path(row.staging_path)
            if self._policy_for(row.kind).keep_after_upload:
                self._staging.retain(staged)
                self.store.mark_done(row.id)  # tombstone dedups re-enqueues of the same key
            else:
                self._staging.unlink(staged)
                self.store.delete(row.id)
