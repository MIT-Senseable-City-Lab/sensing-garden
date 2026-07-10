"""Tests for the finalized-result health audit."""
import importlib.util
import json
from pathlib import Path

# result_health is stdlib-only by design; load it from its file so the tests
# don't drag in cv2/hailo via the bugcam.edge26 package __init__.
_spec = importlib.util.spec_from_file_location(
    "result_health",
    Path(__file__).resolve().parent.parent / "bugcam" / "edge26" / "result_health.py",
)
_result_health = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_result_health)
audit_result_dir = _result_health.audit_result_dir

FLIK_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _write_results(output_dir: Path, tracks: list[dict], confirmed: int | None = None) -> None:
    payload = {
        "source_device": "flick01",
        "summary": {
            "total_detections": sum(t.get("num_detections", 0) for t in tracks),
            "total_tracks": len(tracks),
            "confirmed_tracks": len(tracks) if confirmed is None else confirmed,
            "unconfirmed_tracks": 0,
        },
        "tracks": tracks,
    }
    (output_dir / "results.json").write_text(json.dumps(payload))


def _track(track_id: str) -> dict:
    return {
        "track_id": track_id,
        "final_prediction": {"family": "Apidae", "genus": "Apis", "species": "mellifera"},
        "num_detections": 3,
        "frames": [{"frame_number": 1}],
    }


def _add_crops(output_dir: Path, dir_name: str) -> None:
    crop_dir = output_dir / "crops" / dir_name
    crop_dir.mkdir(parents=True)
    (crop_dir / "frame_0001.jpg").write_bytes(b"jpg")


def _healthy_flik_dir(tmp_path: Path) -> Path:
    output_dir = tmp_path / "flick01" / "20260710_120000"
    output_dir.mkdir(parents=True)
    track_id = f"{FLIK_UUID}_120001"
    (output_dir / ".done").write_text("classified=1\nexpected=1\n")
    _write_results(output_dir, [_track(track_id)])
    _add_crops(output_dir, FLIK_UUID.split("-")[0])  # BugSpot uses first UUID segment
    return output_dir


def test_healthy_flik_dir_passes(tmp_path):
    assert audit_result_dir(_healthy_flik_dir(tmp_path)) == []


def test_healthy_dot_dir_passes(tmp_path):
    # DOT per-track layout: bare track id in results, crops/<track>_<HHMMSS>/
    output_dir = tmp_path / "dot01" / "20260710" / "track003_120500"
    output_dir.mkdir(parents=True)
    (output_dir / ".done").write_text("classified=1\nexpected=1\n")
    _write_results(output_dir, [_track("track003")])
    _add_crops(output_dir, "track003_120500")
    assert audit_result_dir(output_dir) == []


def test_healthy_empty_result_passes(tmp_path):
    output_dir = tmp_path / "flick01" / "20260710_130000"
    output_dir.mkdir(parents=True)
    (output_dir / ".done").write_text("classified=0\nexpected=0\n")
    _write_results(output_dir, [])
    assert audit_result_dir(output_dir) == []


def test_missing_results_json(tmp_path):
    output_dir = tmp_path / "flick01" / "20260710_140000"
    output_dir.mkdir(parents=True)
    (output_dir / ".done").write_text("classified=2\nexpected=2\n")
    problems = audit_result_dir(output_dir)
    assert len(problems) == 1
    assert "results.json is missing" in problems[0]


def test_corrupt_results_json(tmp_path):
    output_dir = _healthy_flik_dir(tmp_path)
    (output_dir / "results.json").write_text("{truncated")
    problems = audit_result_dir(output_dir)
    assert len(problems) == 1
    assert "results.json unreadable" in problems[0]


def test_fewer_tracks_than_expected(tmp_path):
    # Graceful classification failures count toward .completed_tracks, so a dir
    # can reach .done with tracks missing from results.json -- the key scenario.
    output_dir = _healthy_flik_dir(tmp_path)
    (output_dir / ".done").write_text("classified=3\nexpected=3\n")
    problems = audit_result_dir(output_dir)
    assert any("1 track(s) but 3 were expected" in p for p in problems)
    assert any("2 classification(s) failed or were lost" in p for p in problems)


def test_swept_stale_without_counts(tmp_path):
    output_dir = _healthy_flik_dir(tmp_path)
    (output_dir / ".done").write_text("swept=stale\n")
    problems = audit_result_dir(output_dir)
    assert any("finalized by the stale sweep" in p for p in problems)


def test_swept_stale_with_partial_counts(tmp_path):
    output_dir = _healthy_flik_dir(tmp_path)
    (output_dir / ".done").write_text("swept=stale\ncompleted=1\nexpected=4\n")
    problems = audit_result_dir(output_dir)
    assert any("finalized by the stale sweep, not by classification (1/4 classified)" in p for p in problems)
    assert any("1 track(s) but 4 were expected" in p for p in problems)


def test_classified_exceeds_expected(tmp_path):
    output_dir = _healthy_flik_dir(tmp_path)
    (output_dir / ".done").write_text("classified=2\nexpected=1\n")
    _write_results(output_dir, [_track(f"{FLIK_UUID}_120001"), _track(f"{FLIK_UUID}_120001_1")])
    problems = audit_result_dir(output_dir)
    assert any("exceeds expected" in p for p in problems)


def test_track_without_final_prediction(tmp_path):
    output_dir = _healthy_flik_dir(tmp_path)
    broken = _track(f"{FLIK_UUID}_120001")
    broken["final_prediction"] = None
    _write_results(output_dir, [broken])
    problems = audit_result_dir(output_dir)
    assert any("lack a final_prediction" in p for p in problems)


def test_summary_confirmed_count_mismatch(tmp_path):
    output_dir = _healthy_flik_dir(tmp_path)
    _write_results(output_dir, [_track(f"{FLIK_UUID}_120001")], confirmed=5)
    problems = audit_result_dir(output_dir)
    assert any("confirmed_tracks=5 but 1 track(s)" in p for p in problems)


def test_track_without_crop_folder(tmp_path):
    output_dir = tmp_path / "flick01" / "20260710_150000"
    output_dir.mkdir(parents=True)
    (output_dir / ".done").write_text("classified=2\nexpected=2\n")
    tracked = f"{FLIK_UUID}_150001"
    untracked = "99999999-aaaa-bbbb-cccc-000000000000_150002"
    _write_results(output_dir, [_track(tracked), _track(untracked)])
    _add_crops(output_dir, FLIK_UUID.split("-")[0])  # only the first track's crops exist
    problems = audit_result_dir(output_dir)
    assert any(untracked in p and "no crop folder" in p for p in problems)


def test_tracks_but_no_crops_at_all(tmp_path):
    output_dir = tmp_path / "flick01" / "20260710_160000"
    output_dir.mkdir(parents=True)
    (output_dir / ".done").write_text("classified=1\nexpected=1\n")
    _write_results(output_dir, [_track(f"{FLIK_UUID}_160001")])
    problems = audit_result_dir(output_dir)
    assert any("no crop folders on disk" in p for p in problems)


def test_missing_done_marker_is_tolerated(tmp_path):
    # Audit is called right after .done is written; if it vanished (or is
    # unreadable) the audit still judges the rest of the directory.
    output_dir = _healthy_flik_dir(tmp_path)
    (output_dir / ".done").unlink()
    assert audit_result_dir(output_dir) == []
