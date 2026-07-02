"""Tick observability + retry-behavior contract for the upload loop.

SPEC-pollen-upload-observability (titus/specs/). Written before the
implementation: every test here fails on feat/pollen. Transport is faked;
log assertions go through caplog.
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from bugcam.pollen.archive import TarArchiver
from bugcam.pollen.pollen import Pollen, PollenConfig
from bugcam.pollen.presign import PresignError, RateLimitError


class FakeUploader:
    """Records every attempt; raises for keys matching a fail prefix.

    ``fail`` maps key-prefix -> Exception (or True for a generic RuntimeError).
    Mutable so a test can clear it between ticks.
    """

    def __init__(self, fail=None):
        self.fail = dict(fail or {})
        self.attempts = []   # every upload() call, in order
        self.uploaded = []

    def upload(self, row):
        self.attempts.append(row.s3_key)
        for prefix, exc in self.fail.items():
            if row.s3_key.startswith(prefix):
                raise exc if isinstance(exc, Exception) else RuntimeError("boom")
        self.uploaded.append(row.s3_key)


class TickClock:
    """Deterministic clock; advances ``step`` seconds per call (0 = fixed)."""

    def __init__(self, step=60):
        self.now = datetime(2026, 7, 2, 12, 0, 0)
        self.step = timedelta(seconds=step)

    def __call__(self):
        current = self.now
        self.now = current + self.step
        return current


def _config(tmp_path, **kw):
    cfg = PollenConfig(
        db_path=tmp_path / "pollen.db",
        output_root=tmp_path / "out",
        staging_dir=tmp_path / "staging",
        poll_interval=0.01,
        **kw,
    )
    cfg.output_root.mkdir(parents=True, exist_ok=True)
    return cfg


def _write(root: Path, rel: str, content: bytes = b"x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _pollen(cfg, uploader=None, **kw):
    return Pollen(cfg, uploader=uploader or FakeUploader(), **kw)


def _messages(caplog, level=logging.INFO):
    return [r.getMessage() for r in caplog.records if r.levelno >= level]


# --- spec 1: every upload attempt is logged before it starts -----------------

class TestAttemptLogging:
    def test_attempt_logged_with_key_kind_and_attempt_number(self, tmp_path, caplog):
        cfg = _config(tmp_path)
        pol = _pollen(cfg)
        path = _write(cfg.output_root, "flick1/c/results.json", b"{}")
        pol.enqueue_set([path], device="flick1", kind="result")

        with caplog.at_level(logging.INFO):
            pol._tick()

        assert any(
            "uploading" in m and "v1/flick1/c/results.json" in m
            and "kind=result" in m and "attempt 1" in m
            for m in _messages(caplog)
        )


# --- spec 2 / V1: failures carry kind, reason, attempts, "file kept" ---------

class TestFailureLogging:
    def test_archive_failure_logs_kind_reason_and_file_kept(self, tmp_path, caplog):
        cfg = _config(tmp_path, batch=True)
        up = FakeUploader(fail={"v2/archives/": PresignError("/upload-url failed: 400 Bad Request")})
        pol = _pollen(cfg, up, archiver=TarArchiver(), clock=TickClock())
        path = _write(cfg.output_root, "flick1/c/results.json", b"{}")
        pol.enqueue_set([path], device="flick1", kind="result")

        with caplog.at_level(logging.INFO):
            pol._tick()

        warnings = _messages(caplog, logging.WARNING)
        assert any(
            "v2/archives/flick1/" in m and "kind=archive" in m
            and "400" in m and "file kept" in m
            for m in warnings
        )


# --- spec 5 / V2: cleanup always runs, even when the tick aborts -------------

class TestCleanupAlwaysRuns:
    def test_ratelimit_abort_still_cleans_uploaded_rows(self, tmp_path, caplog):
        cfg = _config(tmp_path)
        up = FakeUploader(fail={"v1/flick1/b/": RateLimitError("s3 slowdown")})
        pol = _pollen(cfg, up)
        a = _write(cfg.output_root, "flick1/a/vid.mp4", b"A")
        b = _write(cfg.output_root, "flick1/b/vid.mp4", b"B")
        rid_a = pol.enqueue_set([a], device="flick1", kind="video")[0]
        pol.enqueue_set([b], device="flick1", kind="video")
        staged_a = pol.store.get(rid_a).staging_path

        with caplog.at_level(logging.INFO), pytest.raises(RateLimitError):
            pol._tick()

        # A shipped before the abort: its staged copy must not linger.
        assert not Path(staged_a).exists()
        assert pol.store.get(rid_a) is None
        assert any("abort" in m for m in _messages(caplog, logging.WARNING))


# --- spec 6 / V3: a failed tar is retried, not re-minted ---------------------

class TestArchiveRetryDedup:
    def test_failing_ticks_do_not_mint_new_tars(self, tmp_path):
        cfg = _config(tmp_path, batch=True)
        up = FakeUploader(fail={"v2/archives/": True})
        pol = _pollen(cfg, up, archiver=TarArchiver(), clock=TickClock(step=60))
        path = _write(cfg.output_root, "flick1/c/results.json", b"{}")
        pol.enqueue_set([path], device="flick1", kind="result")

        pol._tick()
        pol._tick()

        archive_rows = [r for r in pol.store.claim_pending() if r.kind == "archive"]
        assert len(archive_rows) == 1, [r.s3_key for r in archive_rows]
        assert len(list(cfg.staging_dir.glob("*.tar"))) == 1

    def test_step1_retry_success_marks_members_uploaded(self, tmp_path):
        cfg = _config(tmp_path, batch=True)
        up = FakeUploader(fail={"v2/archives/": True})
        pol = _pollen(cfg, up, archiver=TarArchiver(), clock=TickClock(step=0))
        path = _write(cfg.output_root, "flick1/c/results.json", b"{}")
        rid = pol.enqueue_set([path], device="flick1", kind="result")[0]
        staged = pol.store.get(rid).staging_path

        pol._tick()          # pack + inline upload fails; tar row left pending
        up.fail.clear()
        pol._tick()          # step-1 retry of the SAME tar succeeds

        # the member must ride the retried tar: marked uploaded, then cleaned
        assert pol.store.get(rid) is None
        assert not Path(staged).exists()
        assert pol.store.pending_count() == 0
        assert list(cfg.staging_dir.glob("*.tar")) == []


# --- spec 3 / V5: silent skips become INFO lines ------------------------------

class TestSkipLogging:
    def test_enqueue_dedup_skip_is_logged(self, tmp_path, caplog):
        cfg = _config(tmp_path, batch=True)
        up = FakeUploader(fail={"v2/archives/": True})
        pol = _pollen(cfg, up, archiver=TarArchiver(), clock=TickClock(step=0))
        a = _write(cfg.output_root, "flick1/c1/results.json", b"{}")
        pol.enqueue_set([a], device="flick1", kind="result")
        pol._tick()  # tar for timestamp T enqueued, upload fails

        # a new member arrives; same fixed timestamp -> same tar key -> dedup
        b = _write(cfg.output_root, "flick1/c2/results.json", b"{}")
        pol.enqueue_set([b], device="flick1", kind="result")
        with caplog.at_level(logging.INFO):
            pol._tick()

        assert any(
            "already queued" in m and "v2/archives/flick1/" in m
            for m in _messages(caplog)
        )


# --- spec 4 / V5: cleanup decisions and tick summary are logged ---------------

class TestCleanupLogging:
    def test_cleaned_row_logged_with_reason(self, tmp_path, caplog):
        cfg = _config(tmp_path)
        pol = _pollen(cfg)
        path = _write(cfg.output_root, "flick1/c/results.json", b"{}")
        pol.enqueue_set([path], device="flick1", kind="result")

        with caplog.at_level(logging.INFO):
            pol._tick()

        msgs = _messages(caplog)
        assert any("cleaned" in m and "v1/flick1/c/results.json" in m for m in msgs)
        assert any("tick summary:" in m and "uploaded=1" in m for m in msgs)

    def test_retained_row_logged_with_reason(self, tmp_path, caplog):
        cfg = _config(tmp_path, delete_after_upload=False)
        pol = _pollen(cfg)
        path = _write(cfg.output_root, "flick1/c/results.json", b"{}")
        pol.enqueue_set([path], device="flick1", kind="result")

        with caplog.at_level(logging.INFO):
            pol._tick()

        assert any(
            "retained" in m and "v1/flick1/c/results.json" in m
            for m in _messages(caplog)
        )


# --- spec 6b / V4: at most videos_per_tick videos, attempts-first order -------

class TestVideoCapPerTick:
    def test_cap_limits_to_one_video_per_tick(self, tmp_path):
        cfg = _config(tmp_path, batch=True, videos_per_tick=1)
        up = FakeUploader(fail={"v1/flick1/a/": True})
        pol = _pollen(cfg, up, archiver=TarArchiver(), clock=TickClock())
        a = _write(cfg.output_root, "flick1/a/vid.mp4", b"A")
        b = _write(cfg.output_root, "flick1/b/vid.mp4", b"B")
        pol.enqueue_set([a, b], device="flick1", kind="video")

        pol._tick()

        # only the first video was attempted; the cap held B back
        assert up.attempts == ["v1/flick1/a/vid.mp4"]

    def test_failing_video_does_not_starve_the_lane(self, tmp_path):
        cfg = _config(tmp_path, batch=True, videos_per_tick=1)
        up = FakeUploader(fail={"v1/flick1/a/": True})
        pol = _pollen(cfg, up, archiver=TarArchiver(), clock=TickClock())
        a = _write(cfg.output_root, "flick1/a/vid.mp4", b"A")
        b = _write(cfg.output_root, "flick1/b/vid.mp4", b"B")
        pol.enqueue_set([a, b], device="flick1", kind="video")

        pol._tick()  # attempts A (fails)
        pol._tick()  # A has attempts=1, B has 0 -> B goes next

        assert up.uploaded == ["v1/flick1/b/vid.mp4"]
        pending = {r.s3_key for r in pol.store.claim_pending()}
        assert pending == {"v1/flick1/a/vid.mp4"}
