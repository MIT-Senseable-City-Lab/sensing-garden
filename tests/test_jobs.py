"""Tests for bugcam jobs command and queue workflow."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from bugcam.cli import app
from bugcam.jobs import ensure_job_dirs, get_job_counts


def test_jobs_help(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(app, ["jobs", "--help"])
    assert result.exit_code == 0
    assert "run" in result.output
    assert "status" in result.output
    assert "retry" in result.output


def test_jobs_run_help(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(app, ["jobs", "run", "--help"])
    assert result.exit_code == 0
    assert "--stage" in result.output
    assert "--watch" in result.output


def test_jobs_status_empty_queue(cli_runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BUGCAM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BUGCAM_IPHONE_WATCH_DIR", str(tmp_path / "iphone"))
    monkeypatch.setenv("BUGCAM_RECORDINGS_DIR", str(tmp_path / "videos"))

    result = cli_runner.invoke(app, ["jobs", "status"])
    assert result.exit_code == 0
    assert "job status" in result.output
    assert "failed" in result.output


def test_jobs_ingest_process_flow(cli_runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    iphone_dir = tmp_path / "iphone"
    record_dir = tmp_path / "videos"
    iphone_dir.mkdir()
    record_dir.mkdir()
    (iphone_dir / "clip.mp4").write_bytes(b"video-data")

    monkeypatch.setenv("BUGCAM_STATE_DIR", str(state_dir))
    monkeypatch.setenv("BUGCAM_IPHONE_WATCH_DIR", str(iphone_dir))
    monkeypatch.setenv("BUGCAM_RECORDINGS_DIR", str(record_dir))

    ingest = cli_runner.invoke(app, ["jobs", "run", "--stage", "ingest"])
    assert ingest.exit_code == 0
    assert "created=1" in ingest.output

    process = cli_runner.invoke(app, ["jobs", "run", "--stage", "process"])
    assert process.exit_code == 0
    assert "processed=1" in process.output

    counts = get_job_counts()
    assert counts["processed"] == 1
    output_dirs = list((state_dir / "outputs").glob("*"))
    assert len(output_dirs) == 1
    assert (output_dirs[0] / "result.json").exists()


def test_jobs_upload_moves_to_completed(cli_runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    iphone_dir = tmp_path / "iphone"
    record_dir = tmp_path / "videos"
    iphone_dir.mkdir()
    record_dir.mkdir()
    (record_dir / "clip.mp4").write_bytes(b"video-data")

    monkeypatch.setenv("BUGCAM_STATE_DIR", str(state_dir))
    monkeypatch.setenv("BUGCAM_IPHONE_WATCH_DIR", str(iphone_dir))
    monkeypatch.setenv("BUGCAM_RECORDINGS_DIR", str(record_dir))
    monkeypatch.setenv("SENSING_GARDEN_API_KEY", "test-key")
    monkeypatch.setenv("API_BASE_URL", "https://example.com")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "aws-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("DEVICE_ID", "device-123")

    cli_runner.invoke(app, ["jobs", "run", "--stage", "ingest"])
    cli_runner.invoke(app, ["jobs", "run", "--stage", "process"])

    mock_client = MagicMock()
    mock_client.videos.upload_video.return_value = {"id": "video-1"}
    with patch("sensing_garden_client.SensingGardenClient", return_value=mock_client):
        upload = cli_runner.invoke(app, ["jobs", "run", "--stage", "upload"])

    assert upload.exit_code == 0
    counts = get_job_counts()
    assert counts["completed"] == 1
    assert counts["failed"] == 0


def test_jobs_retry_failed_process(cli_runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BUGCAM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BUGCAM_IPHONE_WATCH_DIR", str(tmp_path / "iphone"))
    monkeypatch.setenv("BUGCAM_RECORDINGS_DIR", str(tmp_path / "videos"))

    dirs = ensure_job_dirs()
    job = {
        "job_id": "job-1",
        "stage": "failed",
        "source_type": "iphone",
        "source_path": "/tmp/source.mp4",
        "managed_media_path": "/tmp/managed.mp4",
        "original_filename": "source.mp4",
        "fingerprint": "abc",
        "content_type": "video/mp4",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "capture_timestamp": "2026-01-01T00:00:00+00:00",
        "attempts": {"process": 1, "upload": 0},
        "processing": {},
        "upload": {},
        "errors": [{"stage": "process", "message": "boom"}],
        "failed_stage": "process",
    }
    (dirs["failed"] / "job-1.json").write_text(json.dumps(job), encoding="utf-8")

    result = cli_runner.invoke(app, ["jobs", "retry", "--stage", "process"])
    assert result.exit_code == 0
    assert (dirs["unprocessed"] / "job-1.json").exists()


def test_jobs_run_capture_record_requires_all(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(app, ["jobs", "run", "--stage", "ingest", "--capture-record"])
    assert result.exit_code == 1
    assert "requires --stage all" in result.output
