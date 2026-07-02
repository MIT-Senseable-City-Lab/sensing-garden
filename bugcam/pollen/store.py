"""SQLite-backed queue/cache: Pollen's durable spine.

One row per artifact to upload. The store survives restarts so an interrupted
multipart upload can resume from its persisted ``upload_id`` + parts. Lifecycle:
``pending`` -> ``uploading`` -> ``uploaded``; an uploaded row is pruned once its
local file has been cleaned up.

The store is a generic, durable queue: producers decide what to enqueue, dedup is
on the unique ``s3_key``, and cleanup keys on the staged copy.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class UploadStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"      # shipped, awaiting cleanup
    DONE = "done"              # shipped + file retained; a dedup tombstone


@dataclass(frozen=True)
class UploadRow:
    id: int
    staging_path: str          # the hardlinked copy Pollen uploads and cleans up
    kind: str
    s3_key: str
    status: UploadStatus
    metadata: dict[str, Any]
    upload_id: Optional[str]
    parts: list[dict[str, Any]]
    size: Optional[int]
    attempts: int
    producer_name: Optional[str] = None  # original source path, provenance only


_SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    staging_path  TEXT NOT NULL,
    producer_name TEXT,
    kind          TEXT NOT NULL,
    s3_key        TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'pending',
    metadata      TEXT NOT NULL DEFAULT '{}',
    upload_id     TEXT,
    parts         TEXT NOT NULL DEFAULT '[]',
    size          INTEGER,
    attempts      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads(status, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PollenStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # One connection shared across the app + upload-loop threads; every access
        # is serialized through this lock (reentrant so locked writes can call
        # locked read helpers). check_same_thread=False is safe under that lock.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ----- write -----------------------------------------------------------
    def enqueue(
        self,
        staging_path: str,
        kind: str,
        s3_key: str,
        producer_name: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        size: Optional[int] = None,
    ) -> Optional[int]:
        """Queue an artifact. Returns the row id, or None when its s3_key is already
        queued or shipped -- the key is the identity, so a re-enqueue is a no-op
        (produce-site enqueue fires once per artifact; the tombstone dedups rescans)."""
        now = _now()
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO uploads (staging_path, producer_name, kind, s3_key, status, metadata, size, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (staging_path, producer_name, kind, s3_key, UploadStatus.PENDING.value,
                     json.dumps(metadata or {}), size, now, now),
                )
                self._conn.commit()
                return int(cur.lastrowid)
            except sqlite3.IntegrityError:
                return None

    def enqueue_many(self, specs: list[dict[str, Any]]) -> list[int]:
        """Insert a set of rows in one transaction (single lock acquisition) so a
        concurrent ``claim_pending`` observes them all-or-nothing -- a logical set
        never splits across archives. Skips specs whose s3_key already exists.
        Each spec: staging_path, kind, s3_key, [producer_name], [metadata], [size]."""
        now = _now()
        ids: list[int] = []
        with self._lock:
            for spec in specs:
                try:
                    cur = self._conn.execute(
                        "INSERT INTO uploads (staging_path, producer_name, kind, s3_key, status, metadata, size, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (spec["staging_path"], spec.get("producer_name"), spec["kind"], spec["s3_key"],
                         UploadStatus.PENDING.value, json.dumps(spec.get("metadata") or {}), spec.get("size"), now, now),
                    )
                    ids.append(int(cur.lastrowid))
                except sqlite3.IntegrityError:
                    continue  # key already queued/shipped -> dedup
            self._conn.commit()
        return ids

    def mark_uploading(self, row_id: int, upload_id: Optional[str] = None) -> None:
        self._update(row_id, status=UploadStatus.UPLOADING.value, upload_id=upload_id)

    def record_part(self, row_id: int, part_number: int, etag: str) -> None:
        with self._lock:
            parts = self._parts(row_id)
            parts = [p for p in parts if p["part_number"] != part_number]
            parts.append({"part_number": part_number, "etag": etag})
            parts.sort(key=lambda p: p["part_number"])
            self._conn.execute(
                "UPDATE uploads SET parts = ?, updated_at = ? WHERE id = ?",
                (json.dumps(parts), _now(), row_id),
            )
            self._conn.commit()

    def record_attempt(self, row_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE uploads SET attempts = attempts + 1, updated_at = ? WHERE id = ?",
                (_now(), row_id),
            )
            self._conn.commit()

    def mark_uploaded(self, row_id: int) -> None:
        self._update(row_id, status=UploadStatus.UPLOADED.value)

    def mark_done(self, row_id: int) -> None:
        """Retain the file but keep the row as a dedup tombstone."""
        self._update(row_id, status=UploadStatus.DONE.value)

    def reset_multipart(self, row_id: int) -> None:
        """Drop a stale multipart upload id + parts so the upload restarts fresh."""
        with self._lock:
            self._conn.execute(
                "UPDATE uploads SET upload_id = NULL, parts = '[]', updated_at = ? WHERE id = ?",
                (_now(), row_id),
            )
            self._conn.commit()

    def delete(self, row_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM uploads WHERE id = ?", (row_id,))
            self._conn.commit()

    # ----- read ------------------------------------------------------------
    def get(self, row_id: int) -> Optional[UploadRow]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM uploads WHERE id = ?", (row_id,))
            row = cur.fetchone()
            return _to_row(row) if row else None

    def claim_pending(self, limit: Optional[int] = None) -> list[UploadRow]:
        sql = "SELECT * FROM uploads WHERE status IN (?, ?) ORDER BY id"
        params: list[Any] = [UploadStatus.PENDING.value, UploadStatus.UPLOADING.value]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock:
            return [_to_row(r) for r in self._conn.execute(sql, params).fetchall()]

    def all_staging_paths(self) -> set[str]:
        with self._lock:
            return {r["staging_path"] for r in self._conn.execute("SELECT staging_path FROM uploads")}

    def has_key(self, s3_key: str) -> bool:
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM uploads WHERE s3_key = ? LIMIT 1", (s3_key,)
            ).fetchone() is not None

    def prune_missing(self) -> int:
        """Drop shipped rows (uploaded or done tombstones) whose file is gone.

        TODO: this stats ``producer_name`` -- a path outside the upload subsystem's
        own staging -- which is the one place we reach into dirs we don't own. It
        exists only to bound the dedup tombstones (keep them until the producer's
        file is gone, so a rescan can't re-upload). Remove this external scan once the
        rest of the codebase is trusted never to re-enqueue an already-shipped key."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, producer_name, staging_path FROM uploads WHERE status IN (?, ?)",
                (UploadStatus.UPLOADED.value, UploadStatus.DONE.value),
            ).fetchall()
            # A tombstone tracks its retained producer file; fall back to the
            # staging path for rows that never had one (e.g. archives).
            gone = [r["id"] for r in rows if not Path(r["producer_name"] or r["staging_path"]).exists()]
            for row_id in gone:
                self._conn.execute("DELETE FROM uploads WHERE id = ?", (row_id,))
            if gone:
                self._conn.commit()
            return len(gone)

    def uploaded_rows(self) -> list[UploadRow]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM uploads WHERE status = ? ORDER BY id", (UploadStatus.UPLOADED.value,)
            )
            return [_to_row(r) for r in cur.fetchall()]

    def count(self, status: UploadStatus) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM uploads WHERE status = ?", (status.value,))
            return int(cur.fetchone()[0])

    def pending_count(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM uploads WHERE status IN (?, ?)",
                (UploadStatus.PENDING.value, UploadStatus.UPLOADING.value),
            )
            return int(cur.fetchone()[0])

    def pending_summary(self) -> dict[str, Any]:
        """Backlog health: how many are queued, the oldest one's enqueue time, and
        the worst attempt count -- so a failing-but-retaining device is visible."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), MIN(created_at), MAX(attempts) FROM uploads WHERE status IN (?, ?)",
                (UploadStatus.PENDING.value, UploadStatus.UPLOADING.value),
            ).fetchone()
        return {"pending": int(row[0]), "oldest_created_at": row[1], "max_attempts": int(row[2] or 0)}

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ----- internals -------------------------------------------------------
    def _parts(self, row_id: int) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute("SELECT parts FROM uploads WHERE id = ?", (row_id,))
            row = cur.fetchone()
            return json.loads(row["parts"]) if row else []

    def _update(self, row_id: int, **fields: Any) -> None:
        with self._lock:
            assignments = ", ".join(f"{name} = ?" for name in fields)
            values = list(fields.values()) + [_now(), row_id]
            self._conn.execute(
                f"UPDATE uploads SET {assignments}, updated_at = ? WHERE id = ?", values
            )
            self._conn.commit()


def _to_row(row: sqlite3.Row) -> UploadRow:
    return UploadRow(
        id=row["id"],
        staging_path=row["staging_path"],
        producer_name=row["producer_name"],
        kind=row["kind"],
        s3_key=row["s3_key"],
        status=UploadStatus(row["status"]),
        metadata=json.loads(row["metadata"]),
        upload_id=row["upload_id"],
        parts=json.loads(row["parts"]),
        size=row["size"],
        attempts=row["attempts"],
    )
