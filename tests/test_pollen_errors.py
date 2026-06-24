"""Upload error handling: rate-limit detection, backoff, and the guarantee that a
failed upload keeps its data (never deleted) and retries -- matching old bugcam.
"""
import time

import pytest

from bugcam.pollen.pollen import Pollen, PollenConfig
from bugcam.pollen.presign import Presigner, RateLimitError
from bugcam.pollen.store import UploadStatus
from bugcam.pollen.transport import Uploader


# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return {"upload_url": "u", "upload_id": "UP"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, resp):
        self._resp = resp

    def post(self, url, json=None, headers=None, timeout=None):
        return self._resp

    def put(self, url, data=None, headers=None):
        return self._resp


class TestPresignRateLimit:
    def test_429_raises_rate_limit_with_retry_after(self):
        p = Presigner("https://api", "k", session=_Session(_Resp(429, {"Retry-After": "12"})))
        with pytest.raises(RateLimitError) as exc:
            p.put_url("v1/a/results.json")
        assert exc.value.retry_after == 12

    def test_429_without_header(self):
        p = Presigner("https://api", "k", session=_Session(_Resp(429)))
        with pytest.raises(RateLimitError) as exc:
            p.put_url("k")
        assert exc.value.retry_after is None


class TestTransportRateLimit:
    def test_503_put_raises_rate_limit(self, tmp_path):
        from bugcam.pollen.store import PollenStore

        store = PollenStore(tmp_path / "p.db")
        path = tmp_path / "f.json"
        path.write_bytes(b"x")
        rid = store.enqueue(str(path), "result", "v1/f.json")

        class P:
            def put_url(self, k):
                return "https://s3/put"

        up = Uploader(P(), store, session=_Session(_Resp(503, {"Retry-After": "5"})))
        with pytest.raises(RateLimitError) as exc:
            up.upload(store.get(rid))
        assert exc.value.retry_after == 5


# --------------------------------------------------------------------------- #
class FailingUploader:
    def __init__(self, error=RuntimeError("boom")):
        self.error = error
        self.calls = 0

    def upload(self, row):
        self.calls += 1
        raise self.error


class FlakyUploader:
    """Fails the first N times, then succeeds."""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0
        self.uploaded = []

    def upload(self, row):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient")
        self.uploaded.append(row.s3_key)


def _config(tmp_path, **kw):
    cfg = PollenConfig(
        db_path=tmp_path / "pollen.db", output_root=tmp_path / "out",
        staging_dir=tmp_path / "staging", poll_interval=0.01, **kw,
    )
    cfg.output_root.mkdir(parents=True, exist_ok=True)
    return cfg


def _enqueue_file(pol, name=b"data"):
    path = pol.config.output_root / "flick1" / "c" / "results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"tracks":[{"track_id":"t"}]}', encoding="utf-8")
    return path, pol.enqueue(path, "result")


class TestFailureKeepsData:
    def test_failed_upload_keeps_file_and_row(self, tmp_path):
        pol = Pollen(_config(tmp_path), uploader=FailingUploader())
        path, rid = _enqueue_file(pol)

        failures = pol._tick()

        assert failures == 1
        assert path.exists()                                  # data NOT lost
        row = pol.store.get(rid)
        assert row.status == UploadStatus.PENDING and row.attempts >= 1

    def test_rate_limit_propagates_out_of_tick(self, tmp_path):
        pol = Pollen(_config(tmp_path), uploader=FailingUploader(RateLimitError("429", 7)))
        _enqueue_file(pol)
        with pytest.raises(RateLimitError):
            pol._tick()


class TestFlushNoHang:
    def test_flush_returns_when_uploads_fail(self, tmp_path):
        pol = Pollen(_config(tmp_path), uploader=FailingUploader())
        _enqueue_file(pol)
        # Must return (no progress) rather than spin forever.
        pol.flush()
        assert pol.store.pending_count() == 1  # still queued, retried later


class TestRetryRecovers:
    def test_transient_failure_eventually_uploads(self, tmp_path):
        up = FlakyUploader(fail_times=2)
        pol = Pollen(_config(tmp_path), uploader=up)
        _enqueue_file(pol)
        pol.start()
        try:
            deadline = time.time() + 4.0
            while not up.uploaded and time.time() < deadline:
                time.sleep(0.01)
        finally:
            pol.stop()
        assert up.uploaded == ["v1/flick1/c/results.json"]
        assert up.calls >= 3  # two failures then success
