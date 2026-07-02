"""enqueue_set: atomic set enqueue + explicit device grouping.

A logical set is inserted in one transaction so claim/archive never splits it, and the
batch group comes from the passed ``device``, not a key parse.
"""
from datetime import datetime
from pathlib import Path

from bugcam.pollen.archive import TarArchiver
from bugcam.pollen.pollen import Pollen, PollenConfig


class FakeUploader:
    def __init__(self):
        self.uploaded = []

    def upload(self, row):
        self.uploaded.append(row.s3_key)


def _pollen(tmp_path, **cfg_kw):
    cfg = PollenConfig(
        db_path=tmp_path / "pollen.db",
        output_root=tmp_path / "out",
        staging_dir=tmp_path / "out" / ".pollen-staging",
        poll_interval=0.01,
        **cfg_kw,
    )
    cfg.output_root.mkdir(parents=True, exist_ok=True)
    return Pollen(cfg, uploader=FakeUploader())


def _write(root: Path, rel: str, data: bytes = b"x") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_enqueue_set_inserts_whole_set(tmp_path):
    pol = _pollen(tmp_path)
    out = pol.config.output_root
    files = [_write(out, f"FLIK4/20260101_000000_000000/{n}") for n in ("results.json", "a.jpg", "b.jpg")]
    ids = pol.enqueue_set(files, device="FLIK4", kind="result")
    assert len(ids) == 3
    assert pol.store.pending_count() == 3


def test_enqueue_set_skips_dupes(tmp_path):
    pol = _pollen(tmp_path)
    out = pol.config.output_root
    f = _write(out, "FLIK4/20260101_000000_000000/results.json")
    assert len(pol.enqueue_set([f], device="FLIK4", kind="result")) == 1
    assert pol.enqueue_set([f], device="FLIK4", kind="result") == []  # already queued


def test_enqueue_set_lands_in_one_archive(tmp_path):
    """The primary guarantee: a 3-file set batches into exactly one tar with all 3."""
    pol = _pollen(tmp_path, batch=True)
    pol.archiver = TarArchiver()
    pol._clock = lambda: datetime(2026, 1, 1, 0, 0, 0)
    out = pol.config.output_root
    files = [_write(out, f"FLIK4/20260101_000000_000000/{n}") for n in ("results.json", "a.jpg", "b.jpg")]
    pol.enqueue_set(files, device="FLIK4", kind="result")

    pol._tick()

    tars = [k for k in pol.uploader.uploaded if k.endswith(".tar")]
    assert len(tars) == 1


def test_group_of_uses_passed_device_not_key(tmp_path):
    """Grouping follows the explicit device even when the key would parse differently."""
    pol = _pollen(tmp_path, batch=True)
    pol.archiver = TarArchiver()
    pol._clock = lambda: datetime(2026, 1, 1, 0, 0, 0)
    out = pol.config.output_root
    pol.enqueue_set([_write(out, "FLIK4/20260101_000000_000000/results.json")], device="DEVICE-X", kind="result")

    row = pol.store.claim_pending()[0]
    assert pol._group_of(row) == "DEVICE-X"
