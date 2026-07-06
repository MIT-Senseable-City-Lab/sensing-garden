"""Backlog observability: a failing-but-retaining device must be visible."""
import logging
from datetime import datetime, timedelta

from bugcam.pollen.pollen import Pollen, PollenConfig


def _pollen(tmp_path):
    cfg = PollenConfig(db_path=tmp_path / "p.db", output_root=tmp_path / "out", staging_dir=tmp_path / "s")
    cfg.output_root.mkdir(parents=True, exist_ok=True)
    return Pollen(cfg, presigner=None)


class TestPendingSummary:
    def test_counts_oldest_and_attempts(self, tmp_path):
        pol = _pollen(tmp_path)
        a = pol.store.enqueue("/p/a", "result", "v1/a/results.json")
        pol.store.enqueue("/p/b", "result", "v1/b/results.json")
        c = pol.store.enqueue("/p/c", "result", "v1/c/results.json")
        pol.store.mark_uploaded(c)  # excluded from the backlog
        pol.store.record_attempt(a)
        pol.store.record_attempt(a)

        s = pol.store.pending_summary()
        assert s["pending"] == 2
        assert s["oldest_created_at"] is not None
        assert s["max_attempts"] == 2


class TestUploadStats:
    def test_oldest_age(self, tmp_path):
        pol = _pollen(tmp_path)
        pol.store.enqueue("/p/a", "result", "v1/a/results.json")
        oldest = datetime.fromisoformat(pol.store.pending_summary()["oldest_created_at"])
        stats = pol.upload_stats(now=oldest + timedelta(seconds=125))
        assert 124 <= stats["oldest_age_seconds"] <= 126
        assert stats["pending"] == 1

    def test_empty_queue_age_none(self, tmp_path):
        pol = _pollen(tmp_path)
        assert pol.upload_stats()["oldest_age_seconds"] is None
        assert pol.upload_stats()["pending"] == 0


class TestStuckWarning:
    def test_warns_when_oldest_exceeds_threshold(self, tmp_path, monkeypatch, caplog):
        pol = _pollen(tmp_path)
        monkeypatch.setattr(pol, "upload_stats", lambda: {"pending": 3, "oldest_age_seconds": 5000, "max_attempts": 12})
        with caplog.at_level(logging.ERROR, logger="bugcam.pollen"):
            pol._warn_if_stuck()
        assert any("stuck" in r.getMessage() for r in caplog.records)

    def test_no_warn_when_recent(self, tmp_path, monkeypatch, caplog):
        pol = _pollen(tmp_path)
        monkeypatch.setattr(pol, "upload_stats", lambda: {"pending": 1, "oldest_age_seconds": 10, "max_attempts": 1})
        with caplog.at_level(logging.ERROR, logger="bugcam.pollen"):
            pol._warn_if_stuck()
        assert not any("stuck" in r.getMessage() for r in caplog.records)
