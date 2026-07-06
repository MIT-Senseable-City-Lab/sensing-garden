"""build_pollen wiring + an end-to-end telemetry enqueue/flush with fake transport."""
from pathlib import Path

from bugcam.pollen.integration import build_pollen


def test_build_pollen_uses_state_dir(tmp_path):
    pol = build_pollen(tmp_path / "out", "https://api", "key", state_dir=tmp_path / "state")
    assert pol.config.db_path == tmp_path / "state" / "pollen" / "pollen.db"
    assert pol.config.output_root == tmp_path / "out"
    assert pol.archiver is None  # per-object by default


def test_build_pollen_batch_uses_tar_archiver(tmp_path):
    from bugcam.pollen.archive import TarArchiver

    pol = build_pollen(tmp_path / "out", "https://api", "key", batch=True, state_dir=tmp_path / "state")
    assert isinstance(pol.archiver, TarArchiver)


def test_telemetry_enqueue_and_flush(tmp_path):
    # A heartbeat file produced under output_dir enqueues, uploads (faked), and the
    # queue drains. Pollen leaves the producer file alone -- the run loop deletes it.
    out = tmp_path / "out"
    pol = build_pollen(out, "https://api", "key", state_dir=tmp_path / "state")

    uploaded = []
    pol.uploader = type("U", (), {"upload": lambda self, row: uploaded.append(row.s3_key)})()

    hb = out / "flick1" / "heartbeats" / "20260204_120000.json"
    hb.parent.mkdir(parents=True)
    hb.write_text('{"device_id":"flick1"}', encoding="utf-8")

    staged = pol.store.get(pol.enqueue_set([hb], device="flick1", kind="heartbeat")[0]).staging_path
    pol.flush()

    assert uploaded == ["v1/flick1/heartbeats/20260204_120000.json"]
    assert not Path(staged).exists()  # Pollen's staged copy cleaned
    assert hb.exists()                # producer file left for the run loop to delete
    assert pol.store.pending_count() == 0
