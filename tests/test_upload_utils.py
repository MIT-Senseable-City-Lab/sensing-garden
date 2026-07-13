"""upload_utils: content type by filename.

The skip *decisions* (current-day log, empty result) live in the producers now;
this just covers the one helper genuinely shared with pollen internals
(transport.py). The empty-result check itself lives with its sole caller --
see tests/test_result_publish.py.
"""
from bugcam.pollen.upload_utils import content_type_for


class TestContentType:
    def test_by_extension(self):
        assert content_type_for("results.json") == "application/json"
        assert content_type_for("frame_000000.jpg") == "image/jpeg"
        assert content_type_for("clip.mp4") == "video/mp4"
        assert content_type_for("edge26_20260101.log") == "text/plain"
        assert content_type_for("x.tar") == "application/x-tar"
        assert content_type_for("mystery.bin") == "application/octet-stream"
