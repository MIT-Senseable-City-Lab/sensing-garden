"""End-to-end Pollen uploads against the real backend handlers + ministack S3.

Exercises the upload contract the unit tests can only fake: single presigned
PUT, real multipart assembly, resume-after-interruption, recovery from a
reaped upload, and device-scope enforcement -- all over real HTTP and a real
S3 multipart lifecycle. See conftest.py for the wiring.
"""
from __future__ import annotations

import os

import pytest
import requests

from bugcam.pollen.presign import PresignError
from bugcam.pollen.store import PollenStore
from bugcam.pollen.transport import UploadError, Uploader

pytestmark = pytest.mark.integration

PART_SIZE = 5 * 1024 * 1024  # S3's multipart minimum (last part may be smaller)


class RecordingSession:
    """A real requests.Session that counts PUTs and can fail mid-stream."""

    def __init__(self, fail_after: int | None = None) -> None:
        self._inner = requests.Session()
        self.put_count = 0
        self.fail_after = fail_after

    def put(self, url, data=None, headers=None):
        if self.fail_after is not None and self.put_count >= self.fail_after:
            raise requests.ConnectionError("simulated interruption")
        self.put_count += 1
        return self._inner.put(url, data=data, headers=headers)


def _enqueue(store, tmp_path, key, payload):
    path = tmp_path / "upload.bin"
    path.write_bytes(payload)
    return store.enqueue(str(path), "archive", key)


def test_single_put_small_file(presigner, s3_key, tmp_path, fetch_object):
    store = PollenStore(tmp_path / "p.db")
    payload = os.urandom(64 * 1024)
    rid = _enqueue(store, tmp_path, s3_key, payload)

    # Default threshold (256 MiB) -> small file takes the single presigned PUT.
    Uploader(presigner, store).upload(store.get(rid))

    assert fetch_object(s3_key) == payload


def test_multipart_assembles_large_file(presigner, s3_key, tmp_path, fetch_object):
    store = PollenStore(tmp_path / "p.db")
    payload = os.urandom(12 * 1024 * 1024)  # -> 3 parts at 5 MiB
    rid = _enqueue(store, tmp_path, s3_key, payload)

    Uploader(presigner, store, multipart_threshold=0, part_size=PART_SIZE).upload(store.get(rid))

    assert len(store.get(rid).parts) == 3
    assert fetch_object(s3_key) == payload


def test_resume_after_interruption(presigner, s3_key, tmp_path, fetch_object):
    store = PollenStore(tmp_path / "p.db")
    payload = os.urandom(12 * 1024 * 1024)
    rid = _enqueue(store, tmp_path, s3_key, payload)

    # First attempt uploads one part, then "crashes".
    flaky = RecordingSession(fail_after=1)
    with pytest.raises(requests.ConnectionError):
        Uploader(presigner, store, multipart_threshold=0, part_size=PART_SIZE, session=flaky).upload(store.get(rid))
    assert len(store.get(rid).parts) == 1  # one part persisted

    # Second attempt resumes: only the two remaining parts are uploaded.
    resume = RecordingSession()
    Uploader(presigner, store, multipart_threshold=0, part_size=PART_SIZE, session=resume).upload(store.get(rid))

    assert resume.put_count == 2  # part 1 was not re-sent
    assert fetch_object(s3_key) == payload


def test_recovery_when_upload_reaped(presigner, s3, output_bucket, s3_key, tmp_path, fetch_object):
    store = PollenStore(tmp_path / "p.db")
    payload = os.urandom(12 * 1024 * 1024)
    rid = _enqueue(store, tmp_path, s3_key, payload)

    # Get a multipart going, then crash with a live upload id + one part.
    flaky = RecordingSession(fail_after=1)
    with pytest.raises(requests.ConnectionError):
        Uploader(presigner, store, multipart_threshold=0, part_size=PART_SIZE, session=flaky).upload(store.get(rid))
    dead_upload_id = store.get(rid).upload_id
    assert dead_upload_id

    # Simulate the abort-incomplete lifecycle rule reaping the upload.
    s3.abort_multipart_upload(Bucket=output_bucket, Key=s3_key, UploadId=dead_upload_id)

    # Next attempt hits the gone upload, resets, and surfaces UploadError.
    with pytest.raises(UploadError):
        Uploader(presigner, store, multipart_threshold=0, part_size=PART_SIZE).upload(store.get(rid))
    assert store.get(rid).upload_id is None
    assert store.get(rid).parts == []

    # A fresh attempt now succeeds from scratch.
    Uploader(presigner, store, multipart_threshold=0, part_size=PART_SIZE).upload(store.get(rid))
    assert fetch_object(s3_key) == payload


def test_out_of_scope_key_rejected(presigner):
    with pytest.raises(PresignError):
        presigner.create_multipart("v2/archives/not-my-device/x.tar")


def test_unknown_api_key_rejected(presign_url):
    # Exercises the real auth path: an unseeded key fails device lookup -> 401.
    from bugcam.pollen.presign import Presigner

    bad = Presigner(presign_url, "not-a-real-key")
    with pytest.raises(PresignError):
        bad.create_multipart("v2/archives/FLIK2/x.tar")
