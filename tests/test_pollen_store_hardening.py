"""Hardening suite for PollenStore: concurrency, resume, re-enqueue, edge cases.

The store is written by the app thread (enqueue) and the upload-loop thread
(mark_uploading / record_part / mark_uploaded / delete) at the same time, and it
must survive process restarts mid-upload. These tests hammer those seams.
"""
import threading
from pathlib import Path

import pytest

from bugcam.pollen.store import PollenStore, UploadStatus


def _store(tmp_path: Path) -> PollenStore:
    return PollenStore(tmp_path / "pollen.db")


# --------------------------------------------------------------------------- #
class TestConcurrency:
    def test_concurrent_enqueue_distinct_keys(self, tmp_path):
        store = _store(tmp_path)
        n = 200
        barrier = threading.Barrier(8)
        ids: list[int] = []
        lock = threading.Lock()

        def worker(start):
            barrier.wait()
            for i in range(start, start + n // 8):
                rid = store.enqueue(f"/out/{i}", kind="result", s3_key=f"v1/{i}/results.json")
                if rid is not None:
                    with lock:
                        ids.append(rid)

        threads = [threading.Thread(target=worker, args=(k * (n // 8),)) for k in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(ids) == n
        assert len(set(ids)) == n  # unique ids, no collisions
        assert store.pending_count() == n

    def test_concurrent_enqueue_same_key_exactly_one_wins(self, tmp_path):
        store = _store(tmp_path)
        barrier = threading.Barrier(16)
        results: list = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            rid = store.enqueue("/out/x", kind="result", s3_key="v1/x/results.json")
            with lock:
                results.append(rid)

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        winners = [r for r in results if r is not None]
        assert len(winners) == 1
        assert store.pending_count() == 1

    def test_concurrent_reads_during_writes_do_not_error(self, tmp_path):
        store = _store(tmp_path)
        errors: list[Exception] = []
        stop = threading.Event()

        def writer():
            try:
                for i in range(300):
                    rid = store.enqueue(f"/out/{i}", kind="result", s3_key=f"v1/{i}/results.json")
                    if rid and i % 3 == 0:
                        store.mark_uploading(rid, upload_id=f"UP-{i}")
                        store.record_part(rid, 1, "etag")
                        store.mark_uploaded(rid)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                stop.set()

        def reader():
            try:
                while not stop.is_set():
                    store.claim_pending(limit=50)
                    store.count(UploadStatus.UPLOADED)
                    store.pending_count()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"concurrent access raised: {errors}"


# --------------------------------------------------------------------------- #
class TestReEnqueue:
    def test_reenqueue_after_delete_succeeds(self, tmp_path):
        store = _store(tmp_path)
        a = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json")
        store.mark_uploaded(a)
        store.delete(a)
        b = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json")
        assert b is not None and b != a
        assert store.pending_count() == 1

    def test_reenqueue_while_in_flight_preserves_state(self, tmp_path):
        store = _store(tmp_path)
        a = store.enqueue("/out/big.tar", kind="archive", s3_key="v2/archives/d/x.tar")
        store.mark_uploading(a, upload_id="UP-1")
        store.record_part(a, 1, "etag-1")

        again = store.enqueue("/out/big.tar", kind="archive", s3_key="v2/archives/d/x.tar")
        assert again is None  # ignored

        row = store.get(a)
        assert row.status == UploadStatus.UPLOADING
        assert row.upload_id == "UP-1"
        assert row.parts == [{"part_number": 1, "etag": "etag-1"}]


# --------------------------------------------------------------------------- #
class TestOrderingAndResume:
    def test_claim_pending_is_fifo(self, tmp_path):
        store = _store(tmp_path)
        for i in range(20):
            store.enqueue(f"/out/{i}", kind="result", s3_key=f"v1/{i}/results.json")
        keys = [r.s3_key for r in store.claim_pending()]
        assert keys == [f"v1/{i}/results.json" for i in range(20)]

    def test_claim_pending_limit(self, tmp_path):
        store = _store(tmp_path)
        for i in range(20):
            store.enqueue(f"/out/{i}", kind="result", s3_key=f"v1/{i}/results.json")
        assert len(store.claim_pending(limit=5)) == 5

    def test_uploading_rows_are_claimable_for_resume(self, tmp_path):
        # A crash leaves a row 'uploading' with parts; on restart it must be picked
        # up again (not stuck), with its multipart state intact.
        store = _store(tmp_path)
        a = store.enqueue("/out/big.tar", kind="archive", s3_key="v2/archives/d/x.tar")
        store.mark_uploading(a, upload_id="UP-1")
        store.record_part(a, 1, "etag-1")

        reopened = PollenStore(tmp_path / "pollen.db")
        pending = reopened.claim_pending()
        assert [r.id for r in pending] == [a]
        assert pending[0].status == UploadStatus.UPLOADING
        assert pending[0].upload_id == "UP-1"
        assert pending[0].parts == [{"part_number": 1, "etag": "etag-1"}]


# --------------------------------------------------------------------------- #
class TestRecordParts:
    def test_parts_kept_sorted_when_recorded_out_of_order(self, tmp_path):
        store = _store(tmp_path)
        a = store.enqueue("/out/big.tar", kind="archive", s3_key="v2/archives/d/x.tar")
        store.mark_uploading(a, upload_id="UP-1")
        for n in (3, 1, 2, 5, 4):
            store.record_part(a, n, f"etag-{n}")
        numbers = [p["part_number"] for p in store.get(a).parts]
        assert numbers == [1, 2, 3, 4, 5]

    def test_resend_part_replaces_etag(self, tmp_path):
        store = _store(tmp_path)
        a = store.enqueue("/out/big.tar", kind="archive", s3_key="v2/archives/d/x.tar")
        store.record_part(a, 2, "first")
        store.record_part(a, 2, "second")
        parts = store.get(a).parts
        assert parts == [{"part_number": 2, "etag": "second"}]


# --------------------------------------------------------------------------- #
class TestEdgeCases:
    def test_none_metadata_defaults_to_empty_dict(self, tmp_path):
        store = _store(tmp_path)
        a = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json")
        assert store.get(a).metadata == {}

    def test_unicode_and_nested_metadata_roundtrip(self, tmp_path):
        store = _store(tmp_path)
        meta = {"note": "café — 日本語", "nested": {"parts": [1, 2, {"k": "v"}]}, "flag": True}
        a = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json", metadata=meta)
        assert store.get(a).metadata == meta

    def test_large_metadata(self, tmp_path):
        store = _store(tmp_path)
        meta = {"blob": "x" * 100_000, "ids": list(range(1000))}
        a = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json", metadata=meta)
        assert store.get(a).metadata == meta

    def test_size_is_stored(self, tmp_path):
        store = _store(tmp_path)
        a = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json", size=4242)
        assert store.get(a).size == 4242

    def test_get_missing_returns_none(self, tmp_path):
        assert _store(tmp_path).get(999) is None

    def test_delete_missing_is_noop(self, tmp_path):
        store = _store(tmp_path)
        store.delete(999)  # must not raise

    def test_mark_uploading_single_shot_has_no_upload_id(self, tmp_path):
        store = _store(tmp_path)
        a = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json")
        store.mark_uploading(a)
        row = store.get(a)
        assert row.status == UploadStatus.UPLOADING
        assert row.upload_id is None

    def test_many_rows_enqueue_and_claim(self, tmp_path):
        store = _store(tmp_path)
        for i in range(500):
            store.enqueue(f"/out/{i}", kind="result", s3_key=f"v1/{i:04d}/results.json")
        rows = store.claim_pending()
        assert len(rows) == 500
        assert [r.s3_key for r in rows] == [f"v1/{i:04d}/results.json" for i in range(500)]


@pytest.mark.parametrize("kind", ["result", "heartbeat", "log", "archive", "environment"])
def test_kinds_are_stored_verbatim(tmp_path, kind):
    store = _store(tmp_path)
    a = store.enqueue(f"/out/{kind}", kind=kind, s3_key=f"v1/{kind}/x.json")
    assert store.get(a).kind == kind
