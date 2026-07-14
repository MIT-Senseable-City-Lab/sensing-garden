"""Heartbeat payload: incoming-directory backlog plus optional pipeline/upload
sections supplied by `bugcam run`."""
import pytest

from bugcam.commands import heartbeat as hb


@pytest.fixture(autouse=True)
def _fake_system_reads(monkeypatch):
    monkeypatch.setattr(hb, "_read_cpu_temperature_celsius", lambda: 42.0)
    monkeypatch.setattr(hb, "_read_uptime_seconds", lambda: 100.0)


def _payload(input_dir, **kwargs):
    return hb.build_heartbeat_payload("flick01", input_dir, ["dot01"], **kwargs)


class TestIncoming:
    def test_counts_flick_videos_and_bytes(self, tmp_path):
        (tmp_path / "flick01_20260714_120000.mp4").write_bytes(b"abc")
        (tmp_path / "flick01_20260714_121000.mp4").write_bytes(b"abcde")
        (tmp_path / "other_20260714_120000.mp4").write_bytes(b"x")  # wrong device
        (tmp_path / "flick01_notes.txt").write_text("x")  # not a video

        incoming = _payload(tmp_path)["incoming"]

        assert incoming["flick_videos"] == 2
        assert incoming["flick_video_bytes"] == 8
        assert incoming["dot_dirs"] == 0
        assert incoming["ready_dot_tracks"] == 0

    def test_counts_dot_dirs_and_ready_tracks(self, tmp_path):
        ready = tmp_path / "dot01_20260714" / "crops" / "track-a_120000"
        ready.mkdir(parents=True)
        (ready / "done.txt").write_text("")
        not_ready = tmp_path / "dot01_20260714" / "crops" / "track-b_120100"
        not_ready.mkdir()
        (tmp_path / "dot99_20260714").mkdir()  # unconfigured device ignored

        incoming = _payload(tmp_path)["incoming"]

        assert incoming["dot_dirs"] == 1
        assert incoming["ready_dot_tracks"] == 1

    def test_empty_input_dir_reports_zeros(self, tmp_path):
        incoming = _payload(tmp_path)["incoming"]
        assert incoming == {
            "flick_videos": 0,
            "flick_video_bytes": 0,
            "dot_dirs": 0,
            "ready_dot_tracks": 0,
        }


class TestOptionalSections:
    def test_absent_by_default(self, tmp_path):
        payload = _payload(tmp_path)
        assert "pipeline" not in payload
        assert "upload" not in payload

    def test_included_when_supplied(self, tmp_path):
        payload = _payload(
            tmp_path,
            pipeline_status={"video_queue": 3},
            upload_status={"pending": 7},
        )
        assert payload["pipeline"] == {"video_queue": 3}
        assert payload["upload"] == {"pending": 7}
