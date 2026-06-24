"""Recovery when a multipart upload id is dead (reaped by the abort-incomplete
lifecycle rule or otherwise): drop the stale state and restart fresh.
"""
import pytest

from bugcam.pollen.presign import MultipartUploadGoneError, Presigner
from bugcam.pollen.store import PollenStore
from bugcam.pollen.transport import MAX_MULTIPART_ATTEMPTS, UploadError, Uploader


class GonePresigner:
    def __init__(self, gone_on="none"):
        self.gone_on = gone_on
        self.created = []
        self.aborted = []

    def put_url(self, k):
        return "u"

    def create_multipart(self, k):
        self.created.append(k)
        return "UP-NEW"

    def part_url(self, k, upload_id, n):
        if self.gone_on == "part":
            raise MultipartUploadGoneError("gone")
        return f"part-{n}"

    def complete_multipart(self, k, upload_id, parts):
        if self.gone_on == "complete":
            raise MultipartUploadGoneError("gone")

    def abort_multipart(self, k, upload_id):
        self.aborted.append(upload_id)


class _Resp:
    def __init__(self, status=200):
        self.status_code = status
        self.headers = {"ETag": '"e"'}

    def raise_for_status(self):
        pass


class _Session:
    def put(self, url, data=None, headers=None):
        return _Resp()


def _row(store, tmp_path):
    path = tmp_path / "big.tar"
    path.write_bytes(b"ABCDEFGHIJKL")  # 12 bytes -> multiple parts at part_size 5
    return store.enqueue(str(path), "archive", "v2/archives/d/x.tar")


def _uploader(presigner, store):
    return Uploader(presigner, store, multipart_threshold=0, part_size=5, session=_Session())


class TestGoneDetection:
    def test_presign_complete_404_raises_gone(self):
        class R:
            status_code = 404
            headers = {}

        class S:
            def post(self, *a, **k):
                return R()

        p = Presigner("https://api", "k", session=S())
        with pytest.raises(MultipartUploadGoneError):
            p.complete_multipart("k", "UP", [])


class TestRecovery:
    def test_gone_on_complete_resets_state(self, tmp_path):
        store = PollenStore(tmp_path / "p.db")
        rid = _row(store, tmp_path)
        up = _uploader(GonePresigner("complete"), store)
        with pytest.raises(UploadError):
            up.upload(store.get(rid))
        row = store.get(rid)
        assert row.upload_id is None and row.parts == []  # reset -> fresh next time

    def test_gone_on_part_resets_state(self, tmp_path):
        store = PollenStore(tmp_path / "p.db")
        rid = _row(store, tmp_path)
        up = _uploader(GonePresigner("part"), store)
        with pytest.raises(UploadError):
            up.upload(store.get(rid))
        assert store.get(rid).upload_id is None

    def test_stuck_multipart_aborts_old_and_restarts(self, tmp_path):
        store = PollenStore(tmp_path / "p.db")
        rid = _row(store, tmp_path)
        # A stuck upload: an existing id with many failed attempts.
        store.mark_uploading(rid, upload_id="UP-OLD")
        store.record_part(rid, 1, '"old"')
        for _ in range(MAX_MULTIPART_ATTEMPTS):
            store.record_attempt(rid)

        presigner = GonePresigner("none")  # restart succeeds
        _uploader(presigner, store).upload(store.get(rid))

        assert presigner.aborted == ["UP-OLD"]                 # old upload aborted
        assert presigner.created == ["v2/archives/d/x.tar"]    # fresh multipart created
