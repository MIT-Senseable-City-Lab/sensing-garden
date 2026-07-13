"""result_publish: the empty-result check and its use in publish_result_dir.

result_is_empty lives here (not in pollen/upload_utils.py) because it has
exactly one caller -- this module -- and decides a produce-side question
(is this finalized dir worth shipping), not an upload-mechanics one.
"""
import json
from pathlib import Path

from bugcam.edge26.result_publish import result_is_empty


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
