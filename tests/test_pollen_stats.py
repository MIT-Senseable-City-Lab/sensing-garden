"""Pollen upload observability: bandwidth window for heartbeats, pending-bytes
backlog, the heartbeat priority lane, and immediate path upload."""
from datetime import datetime

import pytest

from bugcam.pollen.archive import TarArchiver
from bugcam.pollen.pollen import Pollen, PollenConfig
from bugcam.pollen.transport import TransferStats, Uploader


class FakeResponse:
    status_code = 200
    headers: dict = {}

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self):
        self.puts = []

    def put(self, url, data=None, headers=None, timeout=None):
        self.puts.append((url, data))
        return FakeResponse()


class FakePresigner:
    def put_url(self, s3_key):
        return f"https://s3.example/{s3_key}"


class FakeUploader:
    def __init__(self):
        self.uploaded = []
        self.uploaded_bytes = []

    def upload(self, row):
        self.uploaded.append(row.s3_key)

    def upload_bytes(self, s3_key, data, content_type=None):
        self.uploaded_bytes.append((s3_key, data, content_type))


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


def _write(root, rel, content=b"x"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class TestTransferStats:
    def test_drain_reports_window_and_resets(self):
        stats = TransferStats()
        stats.record(1_500_000, 1.0)
        stats.record(500_000, 1.0)

        window = stats.drain()
        assert window["bytes_uploaded"] == 2_000_000
        assert window["upload_seconds"] == pytest.approx(2.0)
        assert window["avg_mbps"] == pytest.approx(1.0)

        empty = stats.drain()
        assert empty["bytes_uploaded"] == 0
        assert empty["avg_mbps"] is None

    def test_uploader_put_records_transfer(self):
        uploader = Uploader(FakePresigner(), store=None, session=FakeSession())
        uploader.upload_bytes("v1/flick01/heartbeats/h.json", b"abcdef")

        window = uploader.transfer_stats.drain()
        assert window["bytes_uploaded"] == 6
        assert window["upload_seconds"] >= 0.0


class TestPendingBytes:
    def test_upload_stats_reports_pending_bytes(self, tmp_path):
        cfg = _config(tmp_path)
        pol = Pollen(cfg, uploader=FakeUploader())
        _writes = [
            _write(cfg.output_root, "flick1/a/results.json", b"abc"),
            _write(cfg.output_root, "flick1/b/results.json", b"abcde"),
        ]
        pol.enqueue_set(_writes, device="flick1", kind="result")

        assert pol.upload_stats()["pending_bytes"] == 8

        pol._tick()
        assert pol.upload_stats()["pending_bytes"] == 0


class TestStats:
    def test_stats_merges_backlog_and_transfer_window(self, tmp_path):
        cfg = _config(tmp_path)
        uploader = FakeUploader()
        uploader.transfer_stats = TransferStats()
        uploader.transfer_stats.record(1_000_000, 1.0)
        pol = Pollen(cfg, uploader=uploader)

        stats = pol.stats()
        assert stats["pending"] == 0
        assert stats["pending_bytes"] == 0
        assert stats["bytes_uploaded"] == 1_000_000
        assert stats["avg_mbps"] == pytest.approx(1.0)

    def test_stats_tolerates_uploader_without_transfer_stats(self, tmp_path):
        pol = Pollen(_config(tmp_path), uploader=FakeUploader())
        stats = pol.stats()
        assert stats["pending"] == 0
        assert "bytes_uploaded" not in stats


class TestHeartbeatPriorityLane:
    def test_batched_ships_heartbeats_individually_and_first(self, tmp_path):
        cfg = _config(tmp_path, batch=True)
        up = FakeUploader()
        pol = Pollen(cfg, uploader=up, archiver=TarArchiver(),
                     clock=lambda: datetime(2026, 7, 14, 13, 0, 0))
        r = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[]}')
        h = _write(cfg.output_root, "flick1/heartbeats/h.json", b"{}")
        pol.enqueue_set([r], device="flick1", kind="result")
        pol.enqueue_set([h], device="flick1", kind="heartbeat")

        pol._tick()

        heartbeat_key = "v1/flick1/heartbeats/h.json"
        assert heartbeat_key in up.uploaded            # not packed into the tar
        assert any(k.endswith(".tar") for k in up.uploaded)
        tar_idx = next(i for i, k in enumerate(up.uploaded) if k.endswith(".tar"))
        assert up.uploaded.index(heartbeat_key) < tar_idx  # ships before archives
        assert pol.store.pending_count() == 0

    def test_unbatched_ships_heartbeats_before_other_kinds(self, tmp_path):
        cfg = _config(tmp_path)
        up = FakeUploader()
        pol = Pollen(cfg, uploader=up)
        v = _write(cfg.output_root, "flick1/videos/clip.mp4", b"vid")
        h = _write(cfg.output_root, "flick1/heartbeats/h.json", b"{}")
        pol.enqueue_set([v], device="flick1", kind="video")
        pol.enqueue_set([h], device="flick1", kind="heartbeat")

        pol._tick()

        assert up.uploaded[0] == "v1/flick1/heartbeats/h.json"


class TestUploadPathNow:
    def test_uploads_bytes_at_derived_key(self, tmp_path):
        cfg = _config(tmp_path)
        up = FakeUploader()
        pol = Pollen(cfg, uploader=up)
        path = _write(cfg.output_root, "flick1/heartbeats/h.json", b'{"ok":1}')

        pol.upload_path_now(path)

        assert up.uploaded_bytes == [
            ("v1/flick1/heartbeats/h.json", b'{"ok":1}', "application/json"),
        ]
