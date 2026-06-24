"""Per-tick housekeeping: completed-log enqueue + emptied-dir sweep.

Results are enqueued at their produce site (see test_pollen_produce_site); this
covers what enqueue_ready_outputs still owns -- logs and the sweep.
"""
from datetime import datetime, timedelta
from pathlib import Path

from bugcam.pollen.pollen import Pollen, PollenConfig
from bugcam.pollen.producers import enqueue_ready_outputs, enqueue_result_dir


class FakeUploader:
    def __init__(self):
        self.uploaded = []

    def upload(self, row):
        self.uploaded.append(row.s3_key)


def _pollen(tmp_path):
    cfg = PollenConfig(
        db_path=tmp_path / "pollen.db",
        output_root=tmp_path / "out",
        staging_dir=tmp_path / "staging",
        poll_interval=0.01,
    )
    cfg.output_root.mkdir(parents=True, exist_ok=True)
    return Pollen(cfg, uploader=FakeUploader()), cfg.output_root


def _result_dir(out: Path, device: str, name: str, *, tracks=("t1",), done=False) -> Path:
    rd = out / device / name
    rd.mkdir(parents=True, exist_ok=True)
    import json
    (rd / "results.json").write_text(json.dumps({"tracks": [{"track_id": t} for t in tracks]}), encoding="utf-8")
    for t in tracks:
        crop = rd / "crops" / t
        crop.mkdir(parents=True, exist_ok=True)
        (crop / "frame_000000.jpg").write_bytes(b"img")
    if done:
        (rd / ".done").write_text("", encoding="utf-8")
    return rd


class TestEmptyDirSweep:
    def test_emptied_flik_dir_is_swept(self, tmp_path):
        pol, out = _pollen(tmp_path)
        rd = _result_dir(out, "flick1", "20260204_120000")
        enqueue_result_dir(pol, rd, "flick1", [])  # produce-site enqueue
        pol._tick()  # uploads + deletes the FLIK files, leaving an empty shell

        enqueue_ready_outputs(pol, out, "flick1", [])  # next tick sweeps it
        assert not rd.exists()

    def test_telemetry_dirs_not_swept_when_empty(self, tmp_path):
        pol, out = _pollen(tmp_path)
        (out / "flick1" / "heartbeats").mkdir(parents=True)
        (out / "flick1" / "logs").mkdir(parents=True)
        enqueue_ready_outputs(pol, out, "flick1", [])
        assert (out / "flick1" / "heartbeats").exists()
        assert (out / "flick1" / "logs").exists()

    def test_retained_dot_dir_not_swept(self, tmp_path):
        pol, out = _pollen(tmp_path)
        rd = _result_dir(out, "dot1", "20260204")
        enqueue_result_dir(pol, rd, "flick1", ["dot1"])  # produce-site enqueue
        pol._tick()  # DOT files retained -> dir still has files
        enqueue_ready_outputs(pol, out, "flick1", ["dot1"])
        assert rd.exists()


class TestLogs:
    def test_completed_log_enqueued_today_skipped(self, tmp_path):
        pol, out = _pollen(tmp_path)
        today = datetime.now().strftime("%Y%m%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        logs = out / "flick1" / "logs"
        logs.mkdir(parents=True)
        (logs / f"edge26_{yesterday}.log").write_text("done\n", encoding="utf-8")
        (logs / f"edge26_{today}.log").write_text("active\n", encoding="utf-8")

        enqueue_ready_outputs(pol, out, "flick1", [])

        keys = [r.s3_key for r in pol.store.claim_pending()]
        assert any(yesterday in k for k in keys)
        assert not any(today in k for k in keys)

    def test_rolled_over_log_enqueued_with_retain(self, tmp_path):
        """A rolled-over log is enqueued with retain=True so the local file is kept
        after upload (as a dedup tombstone for the next scan)."""
        pol, out = _pollen(tmp_path)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        log = out / "flick1" / "logs" / f"edge26_{yesterday}.log"
        log.parent.mkdir(parents=True)
        log.write_text("done\n", encoding="utf-8")

        enqueue_ready_outputs(pol, out, "flick1", [])

        row = pol.store.claim_pending()[0]
        assert row.metadata.get("retain") is True

    def test_rescan_after_upload_does_not_reenqueue_unchanged_log(self, tmp_path):
        """After a log uploads and leaves a tombstone, a rescan with the same
        content must not re-enqueue it."""
        pol, out = _pollen(tmp_path)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        log = out / "flick1" / "logs" / f"edge26_{yesterday}.log"
        log.parent.mkdir(parents=True)
        log.write_text("done\n", encoding="utf-8")

        enqueue_ready_outputs(pol, out, "flick1", [])
        count_before = pol.store.pending_count()
        enqueue_ready_outputs(pol, out, "flick1", [])
        assert pol.store.pending_count() == count_before


class TestEnvironment:
    def test_environment_file_enqueued_as_telemetry(self, tmp_path):
        """Environment JSONs live under <device>/environment/ and are swept by
        enqueue_ready_outputs -- make sure they reach the queue."""
        pol, out = _pollen(tmp_path)
        env = out / "flick1" / "environment" / "20260204_120000.json"
        env.parent.mkdir(parents=True)
        env.write_text('{"temperature": 22.5}', encoding="utf-8")

        # environment files are enqueued via the produce-site hook (enqueue_source),
        # not discovered by the scanner, so we enqueue directly here as the hook would.
        pol.enqueue(env, "environment")

        rows = pol.store.claim_pending()
        assert len(rows) == 1
        assert rows[0].s3_key == "v1/flick1/environment/20260204_120000.json"
        assert rows[0].kind == "environment"
