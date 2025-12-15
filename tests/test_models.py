"""Tests for bugcam models command."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import urllib.error
from typer.testing import CliRunner
from bugcam.cli import app


def test_models_list_help(cli_runner: CliRunner) -> None:
    """Test models list help."""
    result = cli_runner.invoke(app, ["models", "list", "--help"])
    assert result.exit_code == 0


def test_models_info_help(cli_runner: CliRunner) -> None:
    """Test models info help."""
    result = cli_runner.invoke(app, ["models", "info", "--help"])
    assert result.exit_code == 0


def test_models_download_help(cli_runner: CliRunner) -> None:
    """Test models download help."""
    result = cli_runner.invoke(app, ["models", "download", "--help"])
    assert result.exit_code == 0


def test_models_list_shows_models(cli_runner: CliRunner, temp_resources_dir: Path) -> None:
    """Test models list shows available models."""
    # Patch both cache and local dirs to use our temp directory
    with patch('bugcam.commands.models.MODELS_CACHE_DIR', temp_resources_dir), \
         patch('bugcam.commands.models.LOCAL_RESOURCES_DIR', temp_resources_dir):
        result = cli_runner.invoke(app, ["models", "list"])
        assert result.exit_code == 0
        # Should show the models we created in temp_resources_dir
        assert "yolov8m.hef" in result.output
        assert "yolov8s.hef" in result.output


def test_models_list_no_models(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test models list when no models exist."""
    empty_dir = tmp_path / "empty_resources"
    empty_dir.mkdir()

    with patch('bugcam.commands.models.MODELS_CACHE_DIR', empty_dir), \
         patch('bugcam.commands.models.LOCAL_RESOURCES_DIR', empty_dir):
        result = cli_runner.invoke(app, ["models", "list"])
        assert result.exit_code == 0
        assert "no" in result.output.lower() or "download" in result.output.lower()


def test_models_info_nonexistent(cli_runner: CliRunner) -> None:
    """Test models info with nonexistent model shows error."""
    result = cli_runner.invoke(app, ["models", "info", "nonexistent_model.hef"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_models_info_existing(cli_runner: CliRunner, temp_resources_dir: Path) -> None:
    """Test models info shows details for existing model."""
    with patch('bugcam.commands.models.MODELS_CACHE_DIR', temp_resources_dir), \
         patch('bugcam.commands.models.LOCAL_RESOURCES_DIR', temp_resources_dir):
        result = cli_runner.invoke(app, ["models", "info", "yolov8m.hef"])
        assert result.exit_code == 0
        assert "yolov8m.hef" in result.output
        # Should show size, path, etc.
        assert "Size" in result.output or "KB" in result.output or "MB" in result.output


@pytest.mark.integration
def test_s3_models_accessible() -> None:
    """Verify S3 bucket and models are publicly accessible."""
    import urllib.request
    url = "https://scl-sensing-garden-models.s3.amazonaws.com/yolov8s.hef"
    req = urllib.request.Request(url, method='HEAD')
    response = urllib.request.urlopen(req)
    assert response.status == 200


def test_models_download_http_404_error(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test download handles HTTP 404 error."""
    with patch('bugcam.commands.models.MODELS_CACHE_DIR', tmp_path), \
         patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url='http://test', code=404, msg='Not Found', hdrs={}, fp=None
        )
        result = cli_runner.invoke(app, ["models", "download", "yolov8s"])
        assert result.exit_code == 1
        assert "404" in result.output or "error" in result.output.lower()


def test_models_download_unknown_model(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test download with unknown model name fails."""
    with patch('bugcam.commands.models.MODELS_CACHE_DIR', tmp_path):
        result = cli_runner.invoke(app, ["models", "download", "nonexistent.hef"])
        assert result.exit_code == 1
        assert "unknown" in result.output.lower()


def test_models_download_no_arguments(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test download without arguments shows available models help text."""
    with patch('bugcam.commands.models.MODELS_CACHE_DIR', tmp_path):
        result = cli_runner.invoke(app, ["models", "download"])
        assert result.exit_code == 0
        assert "available models" in result.output.lower()
        assert "yolov8s" in result.output.lower()
        assert "yolov8m" in result.output.lower()


def test_models_download_skips_existing_file(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test download skips file if it already exists."""
    # Create existing model file
    existing_file = tmp_path / "yolov8s.hef"
    existing_file.write_bytes(b"fake model data")

    with patch('bugcam.commands.models.MODELS_CACHE_DIR', tmp_path):
        result = cli_runner.invoke(app, ["models", "download", "yolov8s"])
        assert result.exit_code == 0
        assert "skipping" in result.output.lower() or "already exists" in result.output.lower()
