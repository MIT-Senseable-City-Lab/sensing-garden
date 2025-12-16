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
    assert "start" in result.output
    assert "single" in result.output


def test_record_start_help(cli_runner: CliRunner) -> None:
    """Test record start subcommand help."""
    result = cli_runner.invoke(app, ["record", "start", "--help"])
    assert result.exit_code == 0
    assert "--duration" in result.output
    assert "--interval" in result.output
    assert "--length" in result.output
    assert "--output-dir" in result.output
    assert "--quiet" in result.output


def test_record_single_help(cli_runner: CliRunner) -> None:
    """Test record single subcommand help."""
    result = cli_runner.invoke(app, ["record", "single", "--help"])
    assert result.exit_code == 0
    assert "--length" in result.output
    assert "--output" in result.output


def test_record_start_requires_linux(cli_runner: CliRunner) -> None:
    """Test record start fails on non-Linux."""
    with patch('bugcam.commands.record.platform.system', return_value='Darwin'):
        result = cli_runner.invoke(app, ["record", "start"])
        assert result.exit_code == 1
        assert "Linux" in result.output or "Raspberry Pi" in result.output


def test_record_single_requires_linux(cli_runner: CliRunner) -> None:
    """Test record single fails on non-Linux."""
    with patch('bugcam.commands.record.platform.system', return_value='Darwin'):
        result = cli_runner.invoke(app, ["record", "single"])
        assert result.exit_code == 1
        assert "Linux" in result.output or "Raspberry Pi" in result.output


def test_record_start_validates_interval(cli_runner: CliRunner) -> None:
    """Test record start validates interval parameter."""
    with patch('bugcam.commands.record.platform.system', return_value='Linux'):
        result = cli_runner.invoke(app, ["record", "start", "--interval", "0"])
        assert result.exit_code == 1
        assert "interval" in result.output.lower()


def test_record_start_validates_length(cli_runner: CliRunner) -> None:
    """Test record start validates length parameter."""
    with patch('bugcam.commands.record.platform.system', return_value='Linux'):
        result = cli_runner.invoke(app, ["record", "start", "--length", "0"])
        assert result.exit_code == 1
        assert "length" in result.output.lower()


def test_record_start_validates_length_vs_interval(cli_runner: CliRunner) -> None:
    """Test record start validates length doesn't exceed interval."""
    with patch('bugcam.commands.record.platform.system', return_value='Linux'):
        # Length 120s > interval 1min = 60s
        result = cli_runner.invoke(app, ["record", "start", "--interval", "1", "--length", "120"])
        assert result.exit_code == 1
        assert "interval" in result.output.lower() or "exceed" in result.output.lower()


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


def test_default_output_dir() -> None:
    """Test default output directory is set correctly."""
    from bugcam.commands.record import DEFAULT_OUTPUT_DIR
    assert DEFAULT_OUTPUT_DIR == Path.home() / "bugcam-videos"
