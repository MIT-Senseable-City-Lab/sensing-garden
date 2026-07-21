"""Sampling-effort tracking: how many chunks the camera recorded, and for how long.

CaptureLog accumulates one JSON line per completed chunk in captures/current.jsonl
(durable across crashes). rotate() seals the accumulated lines into a period report
(<period_end>.json) that the run command ships through Pollen like any other
artifact (kind="capture", key v1/<device>/captures/<ts>.json) -- with archive
batching it rides the per-device tar next to the results it describes. The
upload subsystem is untouched: this is just another producer.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

CURRENT_FILENAME = "current.jsonl"
CAPTURES_SUBDIR = "captures"
DEFAULT_REPORT_INTERVAL_SECONDS = 3600.0  # matches the default --upload-poll cadence


class CaptureLog:
    """Durable per-chunk sampling log with periodic report sealing.

    record_chunk() is called from the recorder thread; rotate()/recover() from
    the report loop. The lock only ever guards a rename of current.jsonl (an
    atomic swap-out, near-instant); the slower read/write-report/unlink work
    runs outside it so a rotation in progress never blocks the recorder
    thread's next append."""

    def __init__(
        self,
        captures_dir: Path,
        device_id: str,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.captures_dir = Path(captures_dir)
        self.device_id = device_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._period_start = self._clock()
        self._chunks_captured_total = 0

    @property
    def _current_path(self) -> Path:
        return self.captures_dir / CURRENT_FILENAME

    @property
    def captured_total(self) -> int:
        """Lifetime count of completed chunks this process has seen -- for the
        heartbeat's video-backlog check (captured vs. uploaded). Process-lifetime,
        like uptime_seconds: it does not survive a restart, and the backend
        already treats a drop in a lifetime counter as a reboot, not negative usage."""
        with self._lock:
            return self._chunks_captured_total

    def record_chunk(self, video_path: Path, duration_seconds: float) -> None:
        """Append one completed chunk. Never raises past logging: a sampling-log
        failure must not break the recording loop that calls it."""
        video_path = Path(video_path)
        try:
            size: Optional[int] = video_path.stat().st_size
        except OSError:
            size = None
        entry = {
            "recorded_at": self._clock().isoformat(),
            "video_file": video_path.name,
            "duration_seconds": round(float(duration_seconds), 3),
            "size_bytes": size,
        }
        try:
            with self._lock:
                # Counted here, ahead of the write, so it reflects a chunk having
                # been captured (the caller already has the file) regardless of
                # whether the sampling-log append itself succeeds below.
                self._chunks_captured_total += 1
                self.captures_dir.mkdir(parents=True, exist_ok=True)
                with open(self._current_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
        except OSError:
            logger.error("capture log: could not record chunk %s", video_path.name, exc_info=True)

    def rotate(self) -> Path:
        """Seal the current period into a report (written even when empty: a
        zero-sample period is a signal, not silence) and start the next one.

        Only the rename that swaps current.jsonl out happens under the lock
        (a single near-instant syscall); the read/write-report work that
        follows runs outside it, so record_chunk() from the recorder thread
        is never blocked on rotate()'s I/O.
        """
        with self._lock:
            period_start = self._period_start
            period_end = self._clock()
            rotated_path = self._swap_current_path(period_end)
            self._period_start = period_end

        samples = self._read_samples(rotated_path) if rotated_path else []
        report_path = self._write_report(samples, period_start, period_end)
        if rotated_path is not None:
            rotated_path.unlink(missing_ok=True)
        return report_path

    def recover(self) -> list[Path]:
        """Startup pass: seal a leftover current.jsonl from a prior run (period
        bounds from its sample timestamps) and return every unshipped report,
        oldest first, for the caller to enqueue."""
        with self._lock:
            rotated_path = self._swap_current_path(self._clock())

        if rotated_path is not None:
            samples = self._read_samples(rotated_path)
            if samples:
                stamps = []
                for sample in samples:
                    try:
                        stamps.append(datetime.fromisoformat(sample["recorded_at"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                start = min(stamps) if stamps else self._clock()
                end = max(stamps) if stamps else self._clock()
                self._write_report(samples, start, end)
            rotated_path.unlink(missing_ok=True)

        if not self.captures_dir.is_dir():
            return []
        return sorted(p for p in self.captures_dir.glob("*.json") if p.is_file())

    def _swap_current_path(self, moment: datetime) -> Optional[Path]:
        """Atomically rename current.jsonl out from under record_chunk() --
        which lazily recreates it fresh on its next append, same as it always
        has -- so the caller can process the old file's contents at leisure
        without holding the lock. Returns None if there was nothing to swap."""
        if not self._current_path.exists():
            return None
        rotated_path = self.captures_dir / f".rotating-{moment.strftime('%Y%m%d_%H%M%S_%f')}.jsonl"
        try:
            self._current_path.rename(rotated_path)
        except FileNotFoundError:
            return None
        return rotated_path

    def _read_samples(self, path: Optional[Path] = None) -> list[dict]:
        path = path or self._current_path
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        samples = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("capture log: skipping corrupt line in %s", path)
        return samples

    def _write_report(self, samples: list[dict], period_start: datetime, period_end: datetime) -> Path:
        payload = {
            "device_id": self.device_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "sample_count": len(samples),
            "total_duration_seconds": round(
                sum(s.get("duration_seconds") or 0.0 for s in samples), 3
            ),
            "samples": samples,
        }
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.captures_dir / f"{period_end.strftime('%Y%m%d_%H%M%S')}.json"
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return report_path
