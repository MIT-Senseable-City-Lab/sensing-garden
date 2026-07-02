"""Daily edge26 log files with rollover-driven upload.

The edge26 log is one file per day (``edge26_<YYYYMMDD>.log``). Only a *completed*
file -- one no longer being appended to -- may be uploaded. This module owns that:
``DailyLogHandler`` writes the current day's file and, the first time it emits after
the day rolls over, closes the finished file, opens the new day's, and hands the
finished path to ``on_complete``. ``ship_existing_logs`` enqueues any already-complete
(non-today) logs left by a prior run or crash at startup.

The upload subsystem never scans for logs; it only receives what this pushes -- one
enqueue per completed file, at the moment it completes.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

LOG_PREFIX = "edge26_"
LOG_SUFFIX = ".log"


def _dated_name(day: str) -> str:
    return f"{LOG_PREFIX}{day}{LOG_SUFFIX}"


class DailyLogHandler(logging.StreamHandler):
    """File log handler that rolls to a new dated file when the day changes and
    pushes the completed file to ``on_complete``. Replaces a static FileHandler so a
    device running across midnight both rotates its log and ships the finished one."""

    def __init__(self, log_dir: Path, *, now: Callable[[], datetime] = datetime.now) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._now = now
        self.on_complete: Optional[Callable[[Path], None]] = None
        self._day = self._today()
        super().__init__(self._open(self._day))

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    def _today(self) -> str:
        return self._now().strftime("%Y%m%d")

    def _path(self, day: str) -> Path:
        return self._log_dir / _dated_name(day)

    def _open(self, day: str):
        return open(self._path(day), "a", encoding="utf-8")

    def emit(self, record: logging.LogRecord) -> None:
        day = self._today()
        if day != self._day:
            completed = self._path(self._day)
            self.acquire()
            try:
                old = self.setStream(self._open(day))  # flushes old, installs new
                if old is not None:
                    old.close()
                self._day = day
            finally:
                self.release()
            if self.on_complete is not None:
                try:
                    self.on_complete(completed)
                except Exception:  # shipping must never break logging
                    logging.getLogger(__name__).exception("log ship-on-rollover failed")
        super().emit(record)


def ship_existing_logs(
    enqueue: Callable[[Path], None],
    log_dir: Path,
    *,
    now: Callable[[], datetime] = datetime.now,
) -> int:
    """Enqueue every completed (non-today) log in ``log_dir``. Idempotent: the upload
    subsystem dedups by key, so re-shipping an already-queued log is a no-op."""
    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return 0
    today = now().strftime("%Y%m%d")
    count = 0
    for path in sorted(log_dir.glob(f"{LOG_PREFIX}*{LOG_SUFFIX}")):
        if today in path.name:
            continue
        enqueue(path)
        count += 1
    return count
