"""The Pollen orchestrator: enqueue -> upload -> mark -> delete+prune, plus
lifecycle (start/stop), flush (drain while still accepting), and batched mode.

Transport is faked so nothing touches the network.
"""
import time
from datetime import datetime
from pathlib import Path

from bugcam.pollen.archive import TarArchiver
from bugcam.pollen.pollen import Pollen, PollenConfig
from bugcam.pollen.staging import STAGING_SUBDIR


class FakeUploader:
    def __init__(self, fail_keys=()):
        self.uploaded = []
        self.fail_keys = set(fail_keys)

    def upload(self, row):
        if row.s3_key in self.fail_keys:
            raise RuntimeError("boom")
        self.uploaded.append(row.s3_key)


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


class TestEnqueue:
    def test_derives_key_from_output_root(self, tmp_path):
        cfg = _config(tmp_path)
        pol = _pollen(cfg)
        path = _write(cfg.output_root, "flick1/heartbeats/h.json", b"{}")
        rid = pol.enqueue_set([path], device="flick1", kind="heartbeat")[0]
        assert pol.store.get(rid).s3_key == "v1/flick1/heartbeats/h.json"

class TestTick:
    def test_uploads_then_deletes_and_prunes(self, tmp_path):
        cfg = _config(tmp_path)
        up = FakeUploader()
        pol = _pollen(cfg, up)
        path = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        rid = pol.enqueue_set([path], device="flick1", kind="result")[0]
        staged = pol.store.get(rid).staging_path

        pol._tick()

        assert up.uploaded == ["v1/flick1/c/results.json"]
        assert not Path(staged).exists()  # Pollen drops its own staged copy
        assert path.exists()              # producer file untouched (producer owns cleanup)
        assert pol.store.get(rid) is None

    def test_keep_after_upload_leaves_tombstone(self, tmp_path):
        from bugcam.pollen.store import UploadStatus

        cfg = _config(tmp_path, delete_after_upload=False)  # keep_after_upload for all kinds
        pol = _pollen(cfg)
        path = _write(cfg.output_root, "dot1/20260204/results.json", b'{"tracks":[{"track_id":"t"}]}')
        rid = pol.enqueue_set([path], device="flick1", kind="result")[0]

        pol._tick()

        # row kept as a 'done' tombstone so a re-enqueue of the same key is deduped
        assert pol.store.get(rid).status == UploadStatus.DONE
        assert pol.enqueue_set([path], device="flick1", kind="result") == []
        assert pol.store.pending_count() == 0

    def test_failed_upload_leaves_row_pending(self, tmp_path):
        cfg = _config(tmp_path)
        up = FakeUploader(fail_keys={"v1/flick1/c/results.json"})
        pol = _pollen(cfg, up)
        path = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        rid = pol.enqueue_set([path], device="flick1", kind="result")[0]

        pol._tick()

        assert up.uploaded == []
        assert path.exists()
        row = pol.store.get(rid)
        assert row is not None and row.attempts >= 1


class TestFlush:
    def test_flush_drains_queue(self, tmp_path):
        cfg = _config(tmp_path)
        up = FakeUploader()
        pol = _pollen(cfg, up)
        for i in range(5):
            pol.enqueue_set([_write(cfg.output_root, f"flick1/c{i}/results.json", b'{"tracks":[{"track_id":"t"}]}')], device="flick1", kind="result")

        pol.flush()

        assert len(up.uploaded) == 5
        assert pol.store.pending_count() == 0


class TestLifecycle:
    def test_start_processes_then_stop(self, tmp_path):
        cfg = _config(tmp_path)
        up = FakeUploader()
        pol = _pollen(cfg, up)
        pol.start()
        try:
            pol.enqueue_set([_write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')], device="flick1", kind="result")
            deadline = time.time() + 3.0
            while not up.uploaded and time.time() < deadline:
                time.sleep(0.01)
        finally:
            pol.stop()
        assert up.uploaded == ["v1/flick1/c/results.json"]

    def test_startup_reconcile_failure_does_not_kill_the_loop(self, tmp_path):
        """A crashing startup reconcile() must not take the whole upload thread
        down with it -- ticks (and thus uploads) must still happen afterwards."""
        cfg = _config(tmp_path)
        up = FakeUploader()
        pol = _pollen(cfg, up)
        pol.reconcile = lambda: (_ for _ in ()).throw(RuntimeError("mount unavailable"))
        pol.start()
        try:
            pol.enqueue_set([_write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')], device="flick1", kind="result")
            deadline = time.time() + 3.0
            while not up.uploaded and time.time() < deadline:
                time.sleep(0.01)
        finally:
            pol.stop()
        assert up.uploaded == ["v1/flick1/c/results.json"]


class TestEnqueueSource:
    def test_source_fires_on_tick(self, tmp_path):
        """enqueue_source must be called on every tick — silent breakage here means
        the background scan loop never discovers new outputs."""
        cfg = _config(tmp_path)
        fired = []
        pol = _pollen(cfg, enqueue_source=lambda p: fired.append(p))
        pol._tick()
        assert fired == [pol]

    def test_source_enqueued_items_are_processed_in_same_tick(self, tmp_path):
        """Items enqueued by the source run before claim_pending() in the same tick,
        so they are uploaded without waiting for the next poll interval."""
        cfg = _config(tmp_path)
        up = FakeUploader()
        path = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')

        def source(p):
            p.enqueue_set([path], device="flick1", kind="result")

        pol = _pollen(cfg, up, enqueue_source=source)
        pol._tick()
        assert up.uploaded == ["v1/flick1/c/results.json"]

    def test_source_exception_does_not_abort_tick(self, tmp_path):
        """A crashing source must not stop the rest of the tick — already-pending
        items must still upload."""
        cfg = _config(tmp_path)
        up = FakeUploader()
        path = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        pol = _pollen(cfg, up, enqueue_source=lambda p: (_ for _ in ()).throw(RuntimeError("scan broke")))
        pol.enqueue_set([path], device="flick1", kind="result")
        pol._tick()
        assert up.uploaded == ["v1/flick1/c/results.json"]


class TestBatched:
    def test_batched_uploads_videos_individually(self, tmp_path):
        # Videos must NOT be bundled into the per-device tar (they bloat it past the
        # multipart threshold and trap the small result data); they ship as their own
        # objects while results still batch.
        cfg = _config(tmp_path, batch=True)
        up = FakeUploader()
        pol = _pollen(cfg, up, archiver=TarArchiver(), clock=lambda: datetime(2026, 2, 4, 13, 0, 0))
        r = _write(cfg.output_root, "dot1/20260204/t1/results.json", b'{"tracks":[{"track_id":"t"}]}')
        v = _write(cfg.output_root, "dot1/20260204/videos/clip.mp4", b"vid")
        pol.enqueue_set([r], device="dot1", kind="result")
        pol.enqueue_set([v], device="dot1", kind="video")

        pol._tick()

        assert "v1/dot1/20260204/videos/clip.mp4" in up.uploaded   # shipped individually
        assert any(k.endswith(".tar") for k in up.uploaded)        # results still tarred
        assert pol.store.pending_count() == 0
        # result archive must ship BEFORE the large video, not after
        tar_idx = next(i for i, k in enumerate(up.uploaded) if k.endswith(".tar"))
        assert tar_idx < up.uploaded.index("v1/dot1/20260204/videos/clip.mp4")

    def test_batched_packs_uploads_and_cleans_members(self, tmp_path):
        cfg = _config(tmp_path, batch=True)
        up = FakeUploader()
        pol = _pollen(cfg, up, archiver=TarArchiver(), clock=lambda: datetime(2026, 2, 4, 13, 0, 0))
        a = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        b = _write(cfg.output_root, "flick1/c/crops/t/frame_000000.jpg", b"img")
        pol.enqueue_set([a, b], device="flick1", kind="result")

        pol._tick()

        assert up.uploaded == ["v2/archives/flick1/20260204_130000.tar"]
        assert a.exists() and b.exists()  # producer files untouched; staged copies cleaned
        assert pol.store.pending_count() == 0

    def test_batched_two_devices_produce_separate_archives(self, tmp_path):
        cfg = _config(tmp_path, batch=True)
        up = FakeUploader()
        pol = _pollen(cfg, up, archiver=TarArchiver(), clock=lambda: datetime(2026, 2, 4, 13, 0, 0))
        pol.enqueue_set([_write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')], device="flick1", kind="result")
        pol.enqueue_set([_write(cfg.output_root, "dot1/20260204/results.json", b'{"tracks":[{"track_id":"t"}]}')], device="dot1", kind="result")

        pol._tick()

        keys = set(up.uploaded)
        assert any("flick1" in k for k in keys)
        assert any("dot1" in k for k in keys)
        assert len([k for k in keys if k.endswith(".tar")]) == 2

    def test_batched_archive_failure_leaves_members_pending(self, tmp_path):
        """If the archive upload fails the member rows must stay pending so the
        next tick retries — no silent data loss."""
        cfg = _config(tmp_path, batch=True)
        up = FakeUploader(fail_keys={"v2/archives/flick1/20260204_130000.tar"})
        pol = _pollen(cfg, up, archiver=TarArchiver(), clock=lambda: datetime(2026, 2, 4, 13, 0, 0))
        a = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        pol.enqueue_set([a], device="flick1", kind="result")

        pol._tick()

        assert a.exists()  # file not deleted
        assert pol.store.pending_count() >= 1  # at least one row still queued


class TestStagingDecouplesProducer:
    def test_enqueue_hardlinks_and_records_producer(self, tmp_path):
        cfg = _config(tmp_path)
        pol = _pollen(cfg)
        path = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        row = pol.store.get(pol.enqueue_set([path], device="flick1", kind="result")[0])
        assert row.producer_name == str(path)
        assert Path(row.staging_path) != path
        assert Path(row.staging_path).stat().st_ino == path.stat().st_ino

    def test_upload_survives_producer_deletion(self, tmp_path):
        cfg = _config(tmp_path)

        class ReadingUploader:
            def __init__(self):
                self.read = {}

            def upload(self, row):
                self.read[row.s3_key] = Path(row.staging_path).read_bytes()

        up = ReadingUploader()
        pol = _pollen(cfg, up)
        body = b'{"tracks":[{"track_id":"t"}]}'
        path = _write(cfg.output_root, "flick1/c/results.json", body)
        pol.enqueue_set([path], device="flick1", kind="result")
        path.unlink()  # producer drops its copy before Pollen uploads
        pol.flush()
        assert up.read["v1/flick1/c/results.json"] == body


class TestRetainUploaded:
    def test_uploaded_copy_kept_in_retained_area(self, tmp_path):
        from bugcam.pollen.staging import RETAINED_SUBDIR

        cfg = _config(tmp_path, retain_uploaded=True)
        up = FakeUploader()
        pol = _pollen(cfg, up)
        path = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        staged = Path(pol.store.get(pol.enqueue_set([path], device="flick1", kind="result")[0]).staging_path)

        pol._tick()

        assert up.uploaded == ["v1/flick1/c/results.json"]
        assert not staged.exists()  # moved out of staging
        retained = cfg.output_root / RETAINED_SUBDIR / "flick1/c/results.json"
        assert retained.exists() and retained.read_bytes() == b'{"tracks":[{"track_id":"t"}]}'

    def test_default_does_not_retain(self, tmp_path):
        from bugcam.pollen.staging import RETAINED_SUBDIR

        cfg = _config(tmp_path)  # retain_uploaded defaults False
        pol = _pollen(cfg)
        path = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        pol.enqueue_set([path], device="flick1", kind="result")
        pol._tick()
        assert not (cfg.output_root / RETAINED_SUBDIR).exists() or not any(
            (cfg.output_root / RETAINED_SUBDIR).rglob("*")
        )

    def test_per_kind_policy_overrides_default(self, tmp_path):
        """A per-kind override keeps one kind as a tombstone while others are dropped."""
        from bugcam.pollen.pollen import KindPolicy
        from bugcam.pollen.store import UploadStatus

        cfg = _config(tmp_path, retention_by_kind={"log": KindPolicy(keep_after_upload=True)})
        pol = _pollen(cfg)
        log = _write(cfg.output_root, "flick1/logs/edge26_20260101.log", b"log")
        res = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        log_id = pol.enqueue_set([log], device="flick1", kind="log")[0]
        res_id = pol.enqueue_set([res], device="flick1", kind="result")[0]

        pol._tick()

        assert pol.store.get(log_id).status == UploadStatus.DONE  # kept (tombstone)
        assert pol.store.get(res_id) is None                      # dropped (default policy)


class TestEnqueueDedup:
    def test_existing_key_skips_without_staging(self, tmp_path):
        cfg = _config(tmp_path)
        pol = _pollen(cfg)
        path = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        first = pol.enqueue_set([path], device="flick1", kind="result")[0]
        assert first is not None
        # same key again -> skipped, and no second staged link is created
        assert pol.enqueue_set([path], device="flick1", kind="result") == []
        staged_links = list((cfg.output_root / STAGING_SUBDIR).rglob("*"))
        assert len([p for p in staged_links if p.is_file()]) == 1


class TestReconcile:
    def _orphan(self, cfg):
        link = cfg.output_root / STAGING_SUBDIR / "orphan.json"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.write_text("{}")
        return link

    def test_orphan_link_swept_after_grace(self, tmp_path):
        cfg = _config(tmp_path, reconcile_grace_seconds=0)
        pol = _pollen(cfg)
        orphan = self._orphan(cfg)
        pol.reconcile()
        assert not orphan.exists()

    def test_young_orphan_kept(self, tmp_path):
        cfg = _config(tmp_path, reconcile_grace_seconds=300)
        pol = _pollen(cfg)
        orphan = self._orphan(cfg)
        pol.reconcile()
        assert orphan.exists()  # too young to collect

    def test_referenced_link_not_swept(self, tmp_path):
        cfg = _config(tmp_path, reconcile_grace_seconds=0)
        pol = _pollen(cfg)
        path = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        staged = Path(pol.store.get(pol.enqueue_set([path], device="flick1", kind="result")[0]).staging_path)
        pol.reconcile()
        assert staged.exists()  # referenced by a row

    def test_pending_row_with_vanished_staging_dropped(self, tmp_path):
        cfg = _config(tmp_path)
        pol = _pollen(cfg)
        path = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        rid = pol.enqueue_set([path], device="flick1", kind="result")[0]
        Path(pol.store.get(rid).staging_path).unlink()  # staged copy vanishes
        pol.reconcile()
        assert pol.store.get(rid) is None

    def test_pending_row_with_unreachable_staging_left_alone(self, tmp_path, monkeypatch):
        """A row from a redirected/removed drive whose old mount raises something
        other than ENOENT (a stale/disconnected mount) must not be treated as a
        confirmed-lost upload -- and reconcile() itself must not blow up."""
        cfg = _config(tmp_path)
        pol = _pollen(cfg)
        path = _write(cfg.output_root, "flick1/c/results.json", b'{"tracks":[{"track_id":"t"}]}')
        rid = pol.enqueue_set([path], device="flick1", kind="result")[0]
        staged = Path(pol.store.get(rid).staging_path)

        real_exists = Path.exists

        def flaky_exists(self):
            if self == staged:
                raise OSError("stale NFS file handle")
            return real_exists(self)

        monkeypatch.setattr(Path, "exists", flaky_exists)
        pol.reconcile()  # must not raise
        assert pol.store.get(rid) is not None  # left pending, not guessed at


def test_read_timeout_scales_with_payload():
    """Per-request read timeout scales with payload so a slow large transfer survives,
    while a small one fails fast (the floor)."""
    from bugcam.pollen.transport import Uploader, MIN_READ_TIMEOUT

    up = Uploader(presigner=None, store=None)
    assert up._timeout_for(100) == MIN_READ_TIMEOUT                   # tiny -> floor
    assert up._timeout_for(1500 * 1024 * 1024) > 2200                # 1.5 GB > ~2194s @ 0.7 MB/s
