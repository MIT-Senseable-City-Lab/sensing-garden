"""Tests for bugcam record command."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from typer.testing import CliRunner
from bugcam.cli import app


def test_record_help(cli_runner: CliRunner) -> None:
    """Test record command help."""
    result = cli_runner.invoke(app, ["record", "--help"])
    assert result.exit_code == 0
    assert "single" in result.output


def test_record_single_help(cli_runner: CliRunner) -> None:
    """Test record single subcommand help."""
    result = cli_runner.invoke(app, ["record", "single", "--help"])
    assert result.exit_code == 0
    assert "--length" in result.output
    assert "--output" in result.output
    assert "--resolution" in result.output


def test_record_single_requires_linux(cli_runner: CliRunner) -> None:
    """Test record single fails on non-Linux."""
    with patch('bugcam.commands.record.platform.system', return_value='Darwin'):
        result = cli_runner.invoke(app, ["record", "single"])
        assert result.exit_code == 1
        assert "Linux" in result.output or "Raspberry Pi" in result.output


def test_check_ffmpeg_available() -> None:
    """Test _check_ffmpeg_available function."""
    from bugcam.commands.record import _check_ffmpeg_available

    # Mock ffmpeg exists
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        assert _check_ffmpeg_available() is True

    # Mock ffmpeg missing
    with patch('subprocess.run', side_effect=FileNotFoundError()):
        assert _check_ffmpeg_available() is False


def test_remux_video_success(tmp_path: Path) -> None:
    """Test _remux_video succeeds with ffmpeg."""
    from bugcam.commands.record import _remux_video

    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video data")

    with patch('bugcam.commands.record._check_ffmpeg_available', return_value=True), \
         patch('subprocess.run') as mock_run, \
         patch('os.replace') as mock_replace:
        mock_run.return_value.returncode = 0
        result = _remux_video(video_path)
        assert result is True
        mock_run.assert_called_once()


def test_remux_video_no_ffmpeg(tmp_path: Path) -> None:
    """Test _remux_video skips when ffmpeg unavailable."""
    from bugcam.commands.record import _remux_video

    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video data")

    with patch('bugcam.commands.record._check_ffmpeg_available', return_value=False):
        result = _remux_video(video_path)
        assert result is True  # Returns True (no error, just skipped)


def test_check_disk_space_sufficient(tmp_path: Path) -> None:
    """Test _check_disk_space returns True when sufficient space."""
    from bugcam.commands.record import _check_disk_space

    with patch('shutil.disk_usage') as mock_usage:
        # Mock 500MB free
        mock_usage.return_value = MagicMock(free=500 * 1024 * 1024)
        has_space, free_mb = _check_disk_space(tmp_path)
        assert has_space is True
        assert free_mb == 500


def test_check_disk_space_insufficient(tmp_path: Path) -> None:
    """Test _check_disk_space returns False when insufficient space."""
    from bugcam.commands.record import _check_disk_space

    with patch('shutil.disk_usage') as mock_usage:
        # Mock 100MB free (less than 300MB required)
        mock_usage.return_value = MagicMock(free=100 * 1024 * 1024)
        has_space, free_mb = _check_disk_space(tmp_path)
        assert has_space is False
        assert free_mb == 100


def test_record_single_low_disk_space_exits(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test record single exits when disk space is low."""
    output_file = tmp_path / "test.mp4"

    with patch('bugcam.commands.record.platform.system', return_value='Linux'), \
         patch('bugcam.commands.record._check_camera_available', return_value=True), \
         patch('bugcam.commands.record._check_disk_space', return_value=(False, 50)):
        result = cli_runner.invoke(app, [
            "record", "single",
            "--output", str(output_file),
            "--length", "10"
        ])
        assert result.exit_code == 1
        assert "Insufficient disk space" in result.output
        assert "50MB" in result.output


def test_record_single_uses_resolved_flick_id_for_generated_filename(tmp_path: Path) -> None:
    from bugcam.commands import record

    captured = {}

    with patch('bugcam.commands.record.platform.system', return_value='Linux'), \
         patch('bugcam.commands.record._check_camera_available', return_value=True), \
         patch('bugcam.commands.record._check_disk_space', return_value=(True, 1000)), \
         patch('bugcam.commands.record.get_output_storage_dir', return_value=tmp_path), \
         patch('bugcam.commands.record.resolve_flick_id', return_value='flick-config'), \
         patch('bugcam.commands.record._remux_video', return_value=True), \
         patch('bugcam.commands.record._record_single_video') as mock_record:
        mock_record.side_effect = lambda output, length, quiet, resolution: captured.setdefault("path", output) or True
        record.single(output=None, length=1, flick_id=None, resolution="1080x1080")

    assert captured["path"].parent == tmp_path
    assert captured["path"].name.startswith("flick-config_")
