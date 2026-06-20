"""Tests for upload-orchestration cost fixes: empty results aren't uploaded,
the active log isn't re-uploaded every poll, and an unchanged DOT results.json
isn't re-PUT.

S3 calls are intercepted by patching the upload functions on
``bugcam.commands.upload`` — no network, no AWS.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from bugcam.commands import upload as upload_mod


def _write_results(results_dir: Path, track_ids: list[str]) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    tracks = [{"track_id": t} for t in track_ids]
    payload = {"tracks": tracks, "summary": {"confirmed_tracks": len(tracks)}}
    (results_dir / "results.json").write_text(json.dumps(payload), encoding="utf-8")


def _make_flik_result(output_dir: Path, device: str, chunk: str, track_ids: list[str], *, done: bool = True) -> Path:
    results_dir = output_dir / device / chunk
    _write_results(results_dir, track_ids)
    if done:
        (results_dir / ".done").write_text("", encoding="utf-8")
    return results_dir


def _patch_uploads(mocker):
    """Patch every S3-touching entrypoint used by upload_ready_results."""
    return {
        "upload_directory": mocker.patch.object(upload_mod, "upload_directory"),
        "upload_file": mocker.patch.object(upload_mod, "upload_file"),
        "upload_manifest": mocker.patch.object(upload_mod, "upload_manifest"),
    }


class TestEmptyResultsNotUploaded:
    def test_flik_empty_results_not_uploaded(self, tmp_path, mocker):
        out = tmp_path / "out"
        _make_flik_result(out, "flick1", "chunk_001", [])
        patches = _patch_uploads(mocker)

        processed, manifest_uploaded = upload_mod.upload_ready_results(
            out, "http://api", "k", "flick1", [], delete_after_upload=True, manifest_uploaded=False
        )

        patches["upload_directory"].assert_not_called()
        # Manifest is per-flick and still owed: a result dir exists (even if its
        # contents are empty), so it uploads once. Nothing was processed.
        patches["upload_manifest"].assert_called_once()
        assert (processed, manifest_uploaded) == (0, True)

    def test_flik_empty_results_cleaned_up_locally(self, tmp_path, mocker):
        # Empty dirs are cleaned up locally even when --no-delete-after-upload is
        # set: they are junk, not retained results.
        out = tmp_path / "out"
        results_dir = _make_flik_result(out, "flick1", "chunk_001", [])
        _patch_uploads(mocker)

        upload_mod.upload_ready_results(
            out, "http://api", "k", "flick1", [], delete_after_upload=False, manifest_uploaded=False
        )

        assert not results_dir.exists()

    def test_flik_nonempty_results_uploaded(self, tmp_path, mocker):
        out = tmp_path / "out"
        results_dir = _make_flik_result(out, "flick1", "chunk_002", ["t1"])
        patches = _patch_uploads(mocker)

        processed, manifest_uploaded = upload_mod.upload_ready_results(
            out, "http://api", "k", "flick1", [], delete_after_upload=False, manifest_uploaded=True
        )

        patches["upload_directory"].assert_called_once()
        # call signature: upload_directory(api_url, api_key, local_dir, s3_prefix)
        uploaded_dir = Path(patches["upload_directory"].call_args.args[2])
        assert uploaded_dir == results_dir
        # One dir processed; manifest already uploaded so it stays True and isn't re-sent.
        patches["upload_manifest"].assert_not_called()
        assert (processed, manifest_uploaded) == (1, True)

    def test_flik_zero_tracks_with_media_still_uploaded(self, tmp_path, mocker):
        # "Empty" = zero tracks AND no media. A zero-track dir that still holds a
        # video is NOT empty and must upload.
        out = tmp_path / "out"
        results_dir = _make_flik_result(out, "flick1", "chunk_003", [])
        (results_dir / "videos").mkdir()
        (results_dir / "videos" / "clip.mp4").write_bytes(b"video")
        patches = _patch_uploads(mocker)

        upload_mod.upload_ready_results(
            out, "http://api", "k", "flick1", [], delete_after_upload=False, manifest_uploaded=True
        )

        patches["upload_directory"].assert_called_once()

    def test_dot_empty_results_not_uploaded(self, tmp_path, mocker):
        out = tmp_path / "out"
        _write_results(out / "dot1" / "chunk_001", [])
        patches = _patch_uploads(mocker)

        upload_mod.upload_ready_results(
            out, "http://api", "k", "flick1", ["dot1"], delete_after_upload=False, manifest_uploaded=True
        )

        # Empty DOT dir: skipped entirely, so results.json is never PUT.
        patches["upload_file"].assert_not_called()


class TestDotResultsReupload:
    def _make_dot_result(self, out: Path, dot_id: str, day: str, track_ids: list[str]) -> Path:
        results_dir = out / dot_id / day
        _write_results(results_dir, track_ids)
        for track_id in track_ids:
            crop_dir = results_dir / "crops" / f"{track_id}_120000"
            crop_dir.mkdir(parents=True, exist_ok=True)
            (crop_dir / "frame_000000.jpg").write_bytes(b"x")
        return results_dir

    def test_unchanged_dot_results_makes_no_requests(self, tmp_path, mocker):
        out = tmp_path / "out"
        self._make_dot_result(out, "dot1", "20260101", ["t1"])
        patches = _patch_uploads(mocker)
        args = (out, "http://api", "k", "flick1", ["dot1"])

        # First poll uploads the new track + results.json (asserted precisely in
        # test_results_json_reput_gated_by_content); here it just seeds state.
        processed, _ = upload_mod.upload_ready_results(*args, delete_after_upload=False, manifest_uploaded=True)
        assert processed == 1

        patches["upload_file"].reset_mock()
        patches["upload_directory"].reset_mock()
        processed, _ = upload_mod.upload_ready_results(*args, delete_after_upload=False, manifest_uploaded=True)

        # Second poll, nothing changed: zero HTTP requests (no crop or results.json
        # re-upload) and nothing reported processed.
        assert patches["upload_file"].call_count == 0
        assert patches["upload_directory"].call_count == 0
        assert processed == 0

    def test_changed_dot_results_are_reuploaded(self, tmp_path, mocker):
        out = tmp_path / "out"
        results_dir = self._make_dot_result(out, "dot1", "20260101", ["t1"])
        patches = _patch_uploads(mocker)
        args = (out, "http://api", "k", "flick1", ["dot1"])

        upload_mod.upload_ready_results(*args, delete_after_upload=False, manifest_uploaded=True)
        patches["upload_file"].reset_mock()

        # A new track arrives -> results.json content changes -> it must re-upload.
        self._make_dot_result(out, "dot1", "20260101", ["t1", "t2"])
        upload_mod.upload_ready_results(*args, delete_after_upload=False, manifest_uploaded=True)

        assert patches["upload_file"].call_count > 0

    def test_results_json_reput_gated_by_content(self, tmp_path, mocker):
        out = tmp_path / "out"
        self._make_dot_result(out, "dot1", "20260101", ["t1"])
        patches = _patch_uploads(mocker)
        args = (out, "http://api", "k", "flick1", ["dot1"])

        def results_json_puts():
            # upload_file(api_url, api_key, local_path, s3_key)
            return [c for c in patches["upload_file"].call_args_list
                    if Path(c.args[2]).name == "results.json"]

        upload_mod.upload_ready_results(*args, delete_after_upload=False, manifest_uploaded=True)
        assert len(results_json_puts()) == 1

        patches["upload_file"].reset_mock()
        upload_mod.upload_ready_results(*args, delete_after_upload=False, manifest_uploaded=True)
        assert results_json_puts() == []  # byte-identical -> not re-PUT

        patches["upload_file"].reset_mock()
        self._make_dot_result(out, "dot1", "20260101", ["t1", "t2"])
        upload_mod.upload_ready_results(*args, delete_after_upload=False, manifest_uploaded=True)
        assert len(results_json_puts()) == 1  # content changed -> re-PUT

    def test_dot_dir_never_deleted_even_with_delete_after_upload(self, tmp_path, mocker):
        # Pre-existing invariant (not introduced by this branch): the DOT path is
        # incremental and accumulates tracks across the day, so its dir is kept
        # regardless of delete_after_upload. Only the FLIK path deletes.
        out = tmp_path / "out"
        results_dir = self._make_dot_result(out, "dot1", "20260101", ["t1"])
        _patch_uploads(mocker)

        upload_mod.upload_ready_results(
            out, "http://api", "k", "flick1", ["dot1"], delete_after_upload=True, manifest_uploaded=True
        )

        assert results_dir.exists()


class TestLogReupload:
    def _make_log(self, output_dir: Path, device: str, name: str, content: str = "log line\n") -> Path:
        log_dir = output_dir / device / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_active_log_not_reuploaded_on_growth(self, tmp_path, mocker):
        out = tmp_path / "out"
        today = datetime.now().strftime("%Y%m%d")
        log = self._make_log(out, "flick1", f"edge26_{today}.log")
        up_file = mocker.patch.object(upload_mod, "upload_file")

        upload_mod._upload_log_files(out, "http://api", "k")
        log.write_text(log.read_text() + "more\n" * 100, encoding="utf-8")  # active log grows
        upload_mod._upload_log_files(out, "http://api", "k")

        # Decision: today's (active) log is never uploaded — only completed days are.
        up_file.assert_not_called()

    def test_completed_previous_day_log_uploaded_once(self, tmp_path, mocker):
        # Regression guard: a rolled-over (yesterday's) log uploads exactly once.
        out = tmp_path / "out"
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        self._make_log(out, "flick1", f"edge26_{yesterday}.log")
        up_file = mocker.patch.object(upload_mod, "upload_file")

        upload_mod._upload_log_files(out, "http://api", "k")
        upload_mod._upload_log_files(out, "http://api", "k")

        assert up_file.call_count == 1


class TestHeartbeatReupload:
    def _make_heartbeat(self, output_dir: Path, device: str, name: str, content: str = "{}") -> Path:
        hb_dir = output_dir / device / "heartbeats"
        hb_dir.mkdir(parents=True, exist_ok=True)
        path = hb_dir / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_unchanged_heartbeat_uploaded_once(self, tmp_path, mocker):
        out = tmp_path / "out"
        self._make_heartbeat(out, "flick1", "hb_120000.json")
        up_file = mocker.patch.object(upload_mod, "upload_file")

        assert upload_mod._upload_heartbeat_files(out, "http://api", "k") == 1
        # Second poll, file unchanged: fingerprint matches state -> not re-uploaded.
        assert upload_mod._upload_heartbeat_files(out, "http://api", "k") == 0
        assert up_file.call_count == 1

    def test_changed_heartbeat_reuploaded(self, tmp_path, mocker):
        out = tmp_path / "out"
        path = self._make_heartbeat(out, "flick1", "hb_120000.json")
        up_file = mocker.patch.object(upload_mod, "upload_file")

        assert upload_mod._upload_heartbeat_files(out, "http://api", "k") == 1
        path.write_text('{"extra": "data"}', encoding="utf-8")  # size changes -> new fingerprint
        assert upload_mod._upload_heartbeat_files(out, "http://api", "k") == 1
        assert up_file.call_count == 2


class TestEnvironmentReupload:
    def _make_environment(self, output_dir: Path, device: str, name: str, content: str = "{}") -> Path:
        env_dir = output_dir / device / "environment"
        env_dir.mkdir(parents=True, exist_ok=True)
        path = env_dir / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_unchanged_environment_uploaded_once(self, tmp_path, mocker):
        out = tmp_path / "out"
        self._make_environment(out, "flick1", "env_120000.json")
        up_file = mocker.patch.object(upload_mod, "upload_file")

        assert upload_mod._upload_environment_files(out, "http://api", "k") == 1
        # Second poll, file unchanged: fingerprint matches state -> not re-uploaded.
        assert upload_mod._upload_environment_files(out, "http://api", "k") == 0
        assert up_file.call_count == 1

    def test_changed_environment_reuploaded(self, tmp_path, mocker):
        out = tmp_path / "out"
        path = self._make_environment(out, "flick1", "env_120000.json")
        up_file = mocker.patch.object(upload_mod, "upload_file")

        assert upload_mod._upload_environment_files(out, "http://api", "k") == 1
        path.write_text('{"extra": "data"}', encoding="utf-8")  # size changes -> new fingerprint
        assert upload_mod._upload_environment_files(out, "http://api", "k") == 1
        assert up_file.call_count == 2
