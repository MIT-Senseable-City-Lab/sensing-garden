"""Produce-site result enqueue + finalized-dir cleanup.

Results are enqueued at their produce site (see test_pollen_produce_site); this
covers what ``enqueue_result_dir`` owns -- enqueue and the dir sweep. Logs are no
longer scanned here; see test_log_shipping.
"""
from pathlib import Path

from bugcam.pollen.pollen import Pollen, PollenConfig
from bugcam.edge26.result_publish import publish_result_dir


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
    def test_enqueued_flik_dir_is_removed(self, tmp_path):
        pol, out = _pollen(tmp_path)
        rd = _result_dir(out, "flick1", "20260204_120000")
        publish_result_dir(pol, rd, "flick1", [])  # produce-site enqueue removes the FLIK dir
        assert not rd.exists()

    def test_dot_dir_removed_after_enqueue(self, tmp_path):
        pol, out = _pollen(tmp_path)
        rd = _result_dir(out, "dot1", "20260204")
        publish_result_dir(pol, rd, "flick1", ["dot1"])  # DOT is now a terminal unit -> removed
        assert not rd.exists()


class TestEnvironment:
    def test_environment_file_enqueued_as_telemetry(self, tmp_path):
        """Environment JSONs live under <device>/environment/ and are pushed via the
        produce-site hook -- make sure they reach the queue."""
        pol, out = _pollen(tmp_path)
        env = out / "flick1" / "environment" / "20260204_120000.json"
        env.parent.mkdir(parents=True)
        env.write_text('{"temperature": 22.5}', encoding="utf-8")

        pol.enqueue_set([env], device="flick1", kind="environment")

        rows = pol.store.claim_pending()
        assert len(rows) == 1
        assert rows[0].s3_key == "v1/flick1/environment/20260204_120000.json"
        assert rows[0].kind == "environment"
