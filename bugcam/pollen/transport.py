"""Resumable upload transport.

Small files go up in a single presigned PUT; large files use multipart, with
each completed part persisted to the store as it lands so an interrupted upload
resumes from where it left off rather than restarting. HTTP session is injectable.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from bugcam.pollen.presign import MultipartUploadGoneError, RateLimitError, _parse_retry_after
from bugcam.pollen.store import PollenStore, UploadRow
from bugcam.pollen.upload_utils import content_type_for

try:
    import requests
except ImportError:
    requests = None  # type: ignore

logger = logging.getLogger("bugcam.pollen")

DEFAULT_PART_SIZE = 64 * 1024 * 1024          # 64 MiB
DEFAULT_MULTIPART_THRESHOLD = 256 * 1024 * 1024  # 256 MiB
MAX_MULTIPART_ATTEMPTS = 5  # after this many tries, assume the upload id is dead
DEFAULT_CONNECT_TIMEOUT = 30.0  # seconds; fail fast on an unreachable host
# The per-request read timeout scales with the payload (bytes / this floor rate), so a
# slow-but-steady large transfer (e.g. a 1.5 GB video on ~0.7 MB/s -> multipart parts)
# isn't killed mid-flight, while a tiny PUT still fails fast on a genuine stall.
DEFAULT_MIN_THROUGHPUT = 256 * 1024  # bytes/s (0.25 MB/s)
MIN_READ_TIMEOUT = 60.0  # seconds floor for small payloads


class UploadError(Exception):
    """Raised when an upload fails."""


class Uploader:
    def __init__(
        self,
        presigner: Any,
        store: PollenStore,
        *,
        multipart_threshold: int = DEFAULT_MULTIPART_THRESHOLD,
        part_size: int = DEFAULT_PART_SIZE,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        min_throughput: float = DEFAULT_MIN_THROUGHPUT,
        session: Any = None,
    ) -> None:
        self.presigner = presigner
        self.store = store
        self.multipart_threshold = multipart_threshold
        self.part_size = part_size
        self.connect_timeout = connect_timeout
        self.min_throughput = min_throughput
        self._session = session or (requests.Session() if requests else None)

    def _timeout_for(self, nbytes: int) -> float:
        """A single timeout (both connect and read legs) scaled to the payload. requests
        holds the connect-leg timeout on the socket until the *response* arrives, so a
        large body's send must fit inside it -- a fixed 30s connect leg kills any upload
        that takes >30s to send (e.g. a 150 MB video on a ~0.7 MB/s link). Scaling both
        gives the send a size-proportional budget; small uploads still fail fast (the
        floor). Down hosts are caught by this budget and retried next tick."""
        return max(self.connect_timeout, MIN_READ_TIMEOUT, nbytes / self.min_throughput)

    def upload(self, row: UploadRow) -> None:
        path = Path(row.staging_path)
        size = path.stat().st_size
        content_type = row.metadata.get("content_type") or content_type_for(path.name)
        if size <= self.multipart_threshold:
            self._single(row, path, content_type)
        else:
            self._multipart(row, path, content_type)

    def upload_bytes(self, s3_key: str, data: bytes, content_type: str | None = None) -> None:
        """One-shot presigned PUT of in-memory bytes (no queue, no staging)."""
        self._put(self.presigner.put_url(s3_key), data, content_type)

    def _put(self, url: str, data: bytes, content_type: str | None = None, *, gone_on_404: bool = False) -> Any:
        if self._session is None:
            raise UploadError("no HTTP session available")
        headers = {"Content-Type": content_type} if content_type else {}
        resp = self._session.put(url, data=data, headers=headers, timeout=self._timeout_for(len(data)))
        status = getattr(resp, "status_code", None)
        # S3 throttling comes back as 503 SlowDown; treat it like a rate limit so
        # the loop backs off instead of hammering.
        if status == 503:
            raise RateLimitError("s3 slowdown", retry_after=_parse_retry_after(resp.headers.get("Retry-After")))
        # A part PUT to a reaped multipart upload returns 404 NoSuchUpload.
        if gone_on_404 and status == 404:
            raise MultipartUploadGoneError("part upload gone")
        resp.raise_for_status()
        return resp

    def _single(self, row: UploadRow, path: Path, content_type: str) -> None:
        url = self.presigner.put_url(row.s3_key)
        with open(path, "rb") as handle:
            self._put(url, handle.read(), content_type)

    def _abort_quietly(self, s3_key: str, upload_id: str) -> None:
        try:
            self.presigner.abort_multipart(s3_key, upload_id)
        except Exception:  # noqa: BLE001 - best effort; the upload may already be gone
            pass

    def _multipart(self, row: UploadRow, path: Path, content_type: str) -> None:
        size = path.stat().st_size
        upload_id = row.upload_id
        already_done = {p["part_number"] for p in row.parts}

        # Defensive: a multipart stuck across many attempts is most likely on a
        # dead upload id (e.g. reaped by the abort-incomplete lifecycle rule).
        # Abort it best-effort and restart from scratch.
        if upload_id and row.attempts >= MAX_MULTIPART_ATTEMPTS:
            self._abort_quietly(row.s3_key, upload_id)
            self.store.reset_multipart(row.id)
            upload_id, already_done = None, set()

        if not upload_id:
            upload_id = self.presigner.create_multipart(row.s3_key)
            self.store.mark_uploading(row.id, upload_id=upload_id)
        logger.debug("multipart upload %s (%.0f MB, %.0f MiB parts, attempt %d)",
                     row.s3_key, size / 1e6, self.part_size / 1048576, row.attempts + 1)

        try:
            part_number = 1
            with open(path, "rb") as handle:
                while True:
                    chunk = handle.read(self.part_size)
                    if not chunk:
                        break
                    if part_number not in already_done:
                        url = self.presigner.part_url(row.s3_key, upload_id, part_number)
                        resp = self._put(url, chunk, content_type, gone_on_404=True)
                        etag = resp.headers.get("ETag") or resp.headers.get("etag")
                        if not etag:
                            raise UploadError(f"missing ETag for part {part_number} of {row.s3_key}")
                        self.store.record_part(row.id, part_number, etag)
                        logger.debug("multipart %s part %d uploaded (%.0f MB)",
                                     row.s3_key, part_number, len(chunk) / 1e6)
                    part_number += 1

            parts = self.store.get(row.id).parts
            self.presigner.complete_multipart(row.s3_key, upload_id, parts)
            logger.info("multipart complete %s (%d parts)", row.s3_key, len(parts))
        except MultipartUploadGoneError as exc:
            # The upload was reaped server-side; drop the stale state so the next
            # attempt starts a fresh multipart.
            self.store.reset_multipart(row.id)
            raise UploadError(f"multipart upload gone for {row.s3_key}; will restart") from exc
