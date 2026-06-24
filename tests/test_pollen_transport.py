"""Resumable uploader: single-shot for small files, multipart for large, and
resume of an interrupted multipart from the store's persisted parts.
"""

from bugcam.pollen.store import PollenStore
from bugcam.pollen.transport import Uploader


class FakePresigner:
    def __init__(self):
        self.created = []
        self.completed = []
        self.part_calls = []

    def put_url(self, s3_key):
        return f"https://s3/put/{s3_key}"

    def create_multipart(self, s3_key):
        self.created.append(s3_key)
        return "UP-NEW"

    def part_url(self, s3_key, upload_id, part_number):
        self.part_calls.append((upload_id, part_number))
        return f"https://s3/part/{part_number}"

    def complete_multipart(self, s3_key, upload_id, parts):
        self.completed.append({"upload_id": upload_id, "parts": parts})

    def abort_multipart(self, s3_key, upload_id):
        pass


class FakeResp:
    def __init__(self, etag=None):
        self.headers = {"ETag": etag} if etag else {}

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self):
        self.puts = []

    def put(self, url, data=None, headers=None):
        self.puts.append({"url": url, "data": data, "headers": headers or {}})
        return FakeResp(etag=f'"etag-{len(self.puts)}"')


def _row(store, tmp_path, name, kind, content: bytes):
    path = tmp_path / name
    path.write_bytes(content)
    rid = store.enqueue(str(path), kind=kind, s3_key=f"v1/{name}")
    return store.get(rid)


class TestSingleShot:
    def test_small_file_single_put(self, tmp_path):
        store = PollenStore(tmp_path / "p.db")
        presigner, session = FakePresigner(), FakeSession()
        up = Uploader(presigner, store, multipart_threshold=1024, session=session)
        row = _row(store, tmp_path, "results.json", "result", b'{"tracks":[]}')

        up.upload(row)

        assert len(session.puts) == 1
        assert session.puts[0]["data"] == b'{"tracks":[]}'
        assert session.puts[0]["headers"]["Content-Type"] == "application/json"
        assert presigner.created == []  # not multipart


class TestUploadBytes:
    def test_one_shot_bytes_put(self, tmp_path):
        store = PollenStore(tmp_path / "p.db")
        presigner, session = FakePresigner(), FakeSession()
        up = Uploader(presigner, store, session=session)

        up.upload_bytes("v1/manifest.json", b'{"flick_id":"f"}', "application/json")

        assert session.puts[0]["url"] == "https://s3/put/v1/manifest.json"
        assert session.puts[0]["data"] == b'{"flick_id":"f"}'
        assert session.puts[0]["headers"]["Content-Type"] == "application/json"


class TestMultipart:
    def test_large_file_splits_into_parts(self, tmp_path):
        store = PollenStore(tmp_path / "p.db")
        presigner, session = FakePresigner(), FakeSession()
        up = Uploader(presigner, store, multipart_threshold=0, part_size=5, session=session)
        row = _row(store, tmp_path, "big.tar", "archive", b"ABCDEFGHIJKL")  # 12 bytes -> 5,5,2

        up.upload(row)

        assert presigner.created == ["v1/big.tar"]
        assert [pc[1] for pc in presigner.part_calls] == [1, 2, 3]
        assert [p["data"] for p in session.puts] == [b"ABCDE", b"FGHIJ", b"KL"]
        # parts persisted in the store and handed to complete in order
        stored = store.get(row.id).parts
        assert [p["part_number"] for p in stored] == [1, 2, 3]
        assert presigner.completed[0]["parts"] == stored
        assert store.get(row.id).upload_id == "UP-NEW"

    def test_resume_skips_already_uploaded_parts(self, tmp_path):
        store = PollenStore(tmp_path / "p.db")
        presigner, session = FakePresigner(), FakeSession()
        up = Uploader(presigner, store, multipart_threshold=0, part_size=5, session=session)
        row = _row(store, tmp_path, "big.tar", "archive", b"ABCDEFGHIJKL")
        # Simulate a crash after part 1: upload_id + part 1 already persisted.
        store.mark_uploading(row.id, upload_id="UP-PREV")
        store.record_part(row.id, 1, '"etag-old"')
        row = store.get(row.id)

        up.upload(row)

        assert presigner.created == []  # resumed, no new multipart
        assert [pc[1] for pc in presigner.part_calls] == [2, 3]  # only the missing parts
        assert [p["data"] for p in session.puts] == [b"FGHIJ", b"KL"]
        completed_parts = presigner.completed[0]["parts"]
        assert [p["part_number"] for p in completed_parts] == [1, 2, 3]
        assert completed_parts[0]["etag"] == '"etag-old"'  # kept the original part 1

    def test_resume_persists_no_urls_only_upload_id_and_etags(self, tmp_path):
        # Presigned part URLs are minted fresh each attempt and never stored, so a
        # multi-day gap before resuming is fine for the URLs -- only the multipart
        # upload_id + part etags are persisted (and S3 keeps the upload until aborted).
        import json
        store = PollenStore(tmp_path / "p.db")
        presigner, session = FakePresigner(), FakeSession()
        up = Uploader(presigner, store, multipart_threshold=0, part_size=5, session=session)
        row = _row(store, tmp_path, "big.tar", "archive", b"ABCDEFGHIJKL")
        # interrupt after part 1
        store.mark_uploading(row.id, upload_id="UP-PREV")
        store.record_part(row.id, 1, '"etag-1"')

        persisted = store.get(row.id)
        blob = json.dumps({"upload_id": persisted.upload_id, "parts": persisted.parts})
        assert "http" not in blob  # no presigned URLs persisted anywhere
        assert persisted.upload_id == "UP-PREV"
        assert all(set(p.keys()) == {"part_number", "etag"} for p in persisted.parts)

    def test_empty_file_is_single_shot(self, tmp_path):
        store = PollenStore(tmp_path / "p.db")
        presigner, session = FakePresigner(), FakeSession()
        up = Uploader(presigner, store, multipart_threshold=0, part_size=5, session=session)
        row = _row(store, tmp_path, "empty.json", "result", b"")

        up.upload(row)
        # 0 <= 0 threshold -> single shot, one (empty) PUT, no multipart
        assert presigner.created == []
        assert len(session.puts) == 1
