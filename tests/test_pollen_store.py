"""PollenStore: the SQLite-backed queue/cache that is Pollen's durable spine.

It holds one row per artifact to upload, survives restarts (so an interrupted
multipart upload can resume), and tracks the lifecycle pending -> uploading ->
uploaded, after which the row is pruned once its local file is cleaned up.
"""
import json
from pathlib import Path

from bugcam.pollen.store import PollenStore, UploadStatus


def _store(tmp_path: Path) -> PollenStore:
    return PollenStore(tmp_path / "pollen.db")


class TestEnqueue:
    def test_enqueue_inserts_pending_row(self, tmp_path):
        store = _store(tmp_path)
        row_id = store.enqueue("/out/a/results.json", kind="result", s3_key="v1/a/results.json",
                               metadata={"fingerprint": "abc"})
        rows = store.claim_pending()
        assert len(rows) == 1
        row = rows[0]
        assert row.id == row_id
        assert row.staging_path == "/out/a/results.json"
        assert row.kind == "result"
        assert row.s3_key == "v1/a/results.json"
        assert row.status == UploadStatus.PENDING
        assert row.metadata == {"fingerprint": "abc"}

    def test_enqueue_is_idempotent_on_s3_key(self, tmp_path):
        store = _store(tmp_path)
        first = store.enqueue("/out/a/results.json", kind="result", s3_key="v1/a/results.json")
        second = store.enqueue("/out/a/results.json", kind="result", s3_key="v1/a/results.json")
        assert second is None  # already queued
        assert first is not None
        assert len(store.claim_pending()) == 1

    def test_claim_pending_excludes_uploaded(self, tmp_path):
        store = _store(tmp_path)
        a = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json")
        store.enqueue("/out/b", kind="heartbeat", s3_key="v1/b/heartbeats/h.json")
        store.mark_uploaded(a)
        pending = store.claim_pending()
        assert [r.s3_key for r in pending] == ["v1/b/heartbeats/h.json"]


class TestMultipartState:
    def test_upload_id_and_parts_persist(self, tmp_path):
        store = _store(tmp_path)
        row_id = store.enqueue("/out/big.tar", kind="archive", s3_key="v2/archives/d/x.tar")
        store.mark_uploading(row_id, upload_id="UP-1")
        store.record_part(row_id, part_number=1, etag="etag-1")
        store.record_part(row_id, part_number=2, etag="etag-2")

        # Reopen on the same file: an interrupted upload can resume from here.
        reopened = PollenStore(tmp_path / "pollen.db")
        row = reopened.get(row_id)
        assert row.status == UploadStatus.UPLOADING
        assert row.upload_id == "UP-1"
        assert row.parts == [{"part_number": 1, "etag": "etag-1"},
                             {"part_number": 2, "etag": "etag-2"}]

    def test_record_part_is_idempotent_per_number(self, tmp_path):
        store = _store(tmp_path)
        row_id = store.enqueue("/out/big.tar", kind="archive", s3_key="v2/archives/d/x.tar")
        store.mark_uploading(row_id, upload_id="UP-1")
        store.record_part(row_id, part_number=1, etag="etag-1")
        store.record_part(row_id, part_number=1, etag="etag-1-retry")  # same part re-sent
        row = store.get(row_id)
        assert row.parts == [{"part_number": 1, "etag": "etag-1-retry"}]


class TestLifecycleAndCleanup:
    def test_mark_uploaded_then_prune(self, tmp_path):
        store = _store(tmp_path)
        a = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json")
        b = store.enqueue("/out/b", kind="result", s3_key="v1/b/results.json")
        store.mark_uploaded(a)

        uploaded = store.uploaded_rows()
        assert [r.id for r in uploaded] == [a]

        store.delete(a)
        assert store.get(a) is None
        assert [r.id for r in store.claim_pending()] == [b]

    def test_counts(self, tmp_path):
        store = _store(tmp_path)
        a = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json")
        store.enqueue("/out/b", kind="result", s3_key="v1/b/results.json")
        store.mark_uploaded(a)
        assert store.count(UploadStatus.PENDING) == 1
        assert store.count(UploadStatus.UPLOADED) == 1
        assert store.pending_count() == 1

    def test_attempts_increment(self, tmp_path):
        store = _store(tmp_path)
        row_id = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json")
        store.record_attempt(row_id)
        store.record_attempt(row_id)
        assert store.get(row_id).attempts == 2


class TestPersistence:
    def test_rows_survive_reopen(self, tmp_path):
        store = _store(tmp_path)
        store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json", metadata={"x": 1})
        reopened = PollenStore(tmp_path / "pollen.db")
        rows = reopened.claim_pending()
        assert len(rows) == 1
        assert rows[0].metadata == {"x": 1}

    def test_metadata_roundtrips_json(self, tmp_path):
        store = _store(tmp_path)
        meta = {"fingerprint": "abc", "delete_after": True, "nested": {"a": [1, 2]}}
        row_id = store.enqueue("/out/a", kind="result", s3_key="v1/a/results.json", metadata=meta)
        assert store.get(row_id).metadata == meta
        # stored as JSON text under the hood
        assert isinstance(json.dumps(meta), str)
