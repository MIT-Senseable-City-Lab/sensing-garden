"""The 'done' tombstone and prune_missing.

A retained file (log) leaves a tombstone keyed on its s3_key so a re-enqueue of the
same key is deduped; prune_missing drops the tombstone once its file is gone.
"""
from pathlib import Path

from bugcam.pollen.store import PollenStore, UploadStatus


def _store(tmp_path: Path) -> PollenStore:
    return PollenStore(tmp_path / "pollen.db")


class TestDedup:
    def test_same_key_is_deduped(self, tmp_path):
        store = _store(tmp_path)
        first = store.enqueue("/p", "result", "v1/a/results.json")
        again = store.enqueue("/p", "result", "v1/a/results.json")
        assert first is not None and again is None


class TestTombstone:
    def test_done_excluded_from_claim_and_count(self, tmp_path):
        store = _store(tmp_path)
        rid = store.enqueue("/p", "log", "v1/a/logs/x.log")
        store.mark_uploaded(rid)
        store.mark_done(rid)
        assert store.claim_pending() == []
        assert store.pending_count() == 0
        assert store.get(rid).status == UploadStatus.DONE


class TestPruneMissing:
    def test_prunes_tombstones_whose_file_is_gone(self, tmp_path):
        store = _store(tmp_path)
        present = tmp_path / "present.json"
        present.write_text("{}", encoding="utf-8")

        keep = store.enqueue(str(present), "result", "v1/keep/results.json")
        gone = store.enqueue("/does/not/exist.json", "result", "v1/gone/results.json")
        for rid in (keep, gone):
            store.mark_uploaded(rid)
            store.mark_done(rid)

        pruned = store.prune_missing()

        assert pruned == 1
        assert store.get(gone) is None      # file gone -> tombstone dropped
        assert store.get(keep) is not None  # file present -> tombstone kept
