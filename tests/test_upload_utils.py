"""upload_utils: content type by filename, and the empty-result check.

The skip *decisions* (current-day log, empty result) live in the producers now;
this just covers the shared helpers they call.
"""
import json
from pathlib import Path

from bugcam.pollen.upload_utils import content_type_for, result_is_empty


class TestContentType:
    def test_by_extension(self):
        assert content_type_for("results.json") == "application/json"
        assert content_type_for("frame_000000.jpg") == "image/jpeg"
        assert content_type_for("clip.mp4") == "video/mp4"
        assert content_type_for("edge26_20260101.log") == "text/plain"
        assert content_type_for("x.tar") == "application/x-tar"
        assert content_type_for("mystery.bin") == "application/octet-stream"


def _write_results(results_dir: Path, tracks: list) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "results.json"
    path.write_text(json.dumps({"tracks": tracks}), encoding="utf-8")
    return path


class TestResultIsEmpty:
    def test_zero_tracks_no_media_is_empty(self, tmp_path):
        results = _write_results(tmp_path / "flick1" / "chunk", [])
        assert result_is_empty(results) is True

    def test_with_tracks_not_empty(self, tmp_path):
        results = _write_results(tmp_path / "flick1" / "chunk", [{"track_id": "t1"}])
        assert result_is_empty(results) is False

    def test_zero_tracks_with_media_not_empty(self, tmp_path):
        results_dir = tmp_path / "flick1" / "chunk"
        results = _write_results(results_dir, [])
        (results_dir / "videos").mkdir()
        (results_dir / "videos" / "clip.mp4").write_bytes(b"video")
        assert result_is_empty(results) is False

    def test_zero_tracks_with_top_level_video_sample_not_empty(self, tmp_path):
        # FLIK's every-Nth backdrop sample is saved as <dir>/video.mp4, not
        # under videos/ -- it must keep the result from being dropped.
        results_dir = tmp_path / "flick1" / "chunk"
        results = _write_results(results_dir, [])
        (results_dir / "video.mp4").write_bytes(b"video")
        assert result_is_empty(results) is False

    def test_unreadable_results_not_empty(self, tmp_path):
        assert result_is_empty(tmp_path / "missing.json") is False
