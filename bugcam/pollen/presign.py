"""Pollen's self-contained presigned-URL client.

A small HTTP client over the backend's presign endpoints, deliberately separate
from the rest of bugcam's upload code so Pollen owns its own networking. The
session is injectable for testing.
"""
from __future__ import annotations

from typing import Any, Optional

try:
    import requests
except ImportError:  # requests is always present in practice; keep import lazy-safe
    requests = None  # type: ignore

REQUEST_TIMEOUT_SECONDS = 30


class PresignError(Exception):
    """Raised when a presign request fails."""


class RateLimitError(Exception):
    """Raised when the backend signals throttling (HTTP 429)."""

    def __init__(self, message: str, retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MultipartUploadGoneError(PresignError):
    """The multipart upload no longer exists server-side (aborted or expired)."""


def _parse_retry_after(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class Presigner:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        timeout: int = REQUEST_TIMEOUT_SECONDS,
        session: Any = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._session = session or (requests.Session() if requests else None)

    def _post(self, path: str, payload: dict[str, Any], *, gone_on_404: bool = False) -> dict[str, Any]:
        if self._session is None:
            raise PresignError("no HTTP session available")
        try:
            resp = self._session.post(
                f"{self.api_url}{path}",
                json=payload,
                headers={"x-api-key": self.api_key},
                timeout=self.timeout,
            )
            status = getattr(resp, "status_code", None)
            if status == 429:
                raise RateLimitError(
                    f"{path} rate limited", retry_after=_parse_retry_after(resp.headers.get("Retry-After"))
                )
            if gone_on_404 and status == 404:
                raise MultipartUploadGoneError(f"{path}: multipart upload gone")
            resp.raise_for_status()
            return resp.json()
        except (PresignError, RateLimitError):
            raise
        except Exception as exc:  # noqa: BLE001 - normalize transport/HTTP errors
            raise PresignError(f"{path} failed: {exc}") from exc

    def put_url(self, s3_key: str) -> str:
        # Backend returns {"upload_url": ...} (matches the existing /upload-url API).
        return self._post("/upload-url", {"s3_key": s3_key})["upload_url"]

    def create_multipart(self, s3_key: str) -> str:
        return self._post("/multipart/create", {"s3_key": s3_key})["upload_id"]

    def part_url(self, s3_key: str, upload_id: str, part_number: int) -> str:
        return self._post(
            "/multipart/part-url",
            {"s3_key": s3_key, "upload_id": upload_id, "part_number": part_number},
            gone_on_404=True,
        )["upload_url"]

    def complete_multipart(self, s3_key: str, upload_id: str, parts: list[dict[str, Any]]) -> None:
        self._post(
            "/multipart/complete",
            {"s3_key": s3_key, "upload_id": upload_id, "parts": parts},
            gone_on_404=True,
        )

    def abort_multipart(self, s3_key: str, upload_id: str) -> None:
        self._post("/multipart/abort", {"s3_key": s3_key, "upload_id": upload_id}, gone_on_404=True)
