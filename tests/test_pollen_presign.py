"""Pollen's self-contained presigned-URL client.

A thin HTTP client over the backend's presign endpoints. The network session is
injected so these tests never touch the network.
"""
import pytest

from bugcam.pollen.presign import Presigner, PresignError


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)


def _presigner(responses):
    session = _Session(responses)
    return Presigner("https://api.example.com/v1/", "secret", session=session), session


class TestPresigner:
    def test_put_url(self):
        p, session = _presigner([_Resp({"upload_url": "https://s3/put?sig=1"})])
        url = p.put_url("v1/a/results.json")
        assert url == "https://s3/put?sig=1"
        call = session.calls[0]
        assert call["url"] == "https://api.example.com/v1/upload-url"
        assert call["json"] == {"s3_key": "v1/a/results.json"}
        assert call["headers"]["x-api-key"] == "secret"

    def test_multipart_lifecycle(self):
        p, session = _presigner([
            _Resp({"upload_id": "UP-1"}),
            _Resp({"upload_url": "https://s3/part1"}),
            _Resp({}),
        ])
        upload_id = p.create_multipart("v2/archives/d/x.tar")
        assert upload_id == "UP-1"
        part_url = p.part_url("v2/archives/d/x.tar", "UP-1", 1)
        assert part_url == "https://s3/part1"
        p.complete_multipart("v2/archives/d/x.tar", "UP-1", [{"part_number": 1, "etag": "e1"}])

        endpoints = [c["url"].rsplit("/", 1)[-1] for c in session.calls]
        assert endpoints == ["create", "part-url", "complete"]
        assert session.calls[2]["json"]["parts"] == [{"part_number": 1, "etag": "e1"}]

    def test_abort(self):
        p, session = _presigner([_Resp({})])
        p.abort_multipart("v2/archives/d/x.tar", "UP-1")
        assert session.calls[0]["url"].endswith("/multipart/abort")

    def test_http_error_raises_presign_error(self):
        p, _ = _presigner([_Resp({}, status=500)])
        with pytest.raises(PresignError):
            p.put_url("v1/a/results.json")

    def test_trailing_slash_normalized(self):
        p, session = _presigner([_Resp({"upload_url": "u"})])
        p.put_url("k")
        assert session.calls[0]["url"] == "https://api.example.com/v1/upload-url"
