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
         patch('bugcam.commands.models.list_s3_models', return_value=['yolov8s.hef']), \
         patch('bugcam.commands.models.get_s3_model_size', return_value=10000000), \
         patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url='http://test', code=404, msg='Not Found', hdrs={}, fp=None
        )
        result = cli_runner.invoke(app, ["models", "download", "yolov8s"])
        assert result.exit_code == 1
        assert "404" in result.output or "error" in result.output.lower()


def test_models_download_unknown_model(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test download with unknown model name fails."""
    with patch('bugcam.commands.models.MODELS_CACHE_DIR', tmp_path), \
         patch('bugcam.commands.models.list_s3_models', return_value=['yolov8s.hef', 'yolov8m.hef']):
        result = cli_runner.invoke(app, ["models", "download", "nonexistent.hef"])
        assert result.exit_code == 1
        assert "unknown" in result.output.lower()


def test_models_download_no_arguments(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test download without arguments shows available models help text."""
    with patch('bugcam.commands.models.MODELS_CACHE_DIR', tmp_path), \
         patch('bugcam.commands.models.list_s3_models', return_value=['yolov8s.hef', 'yolov8m.hef']), \
         patch('bugcam.commands.models.get_s3_model_size', return_value=10000000):
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

    with patch('bugcam.commands.models.MODELS_CACHE_DIR', tmp_path), \
         patch('bugcam.commands.models.list_s3_models', return_value=['yolov8s.hef', 'yolov8m.hef']), \
         patch('bugcam.commands.models.get_s3_model_size', return_value=10000000):
        result = cli_runner.invoke(app, ["models", "download", "yolov8s"])
        assert result.exit_code == 0
        assert "skipping" in result.output.lower() or "already exists" in result.output.lower()


def test_list_s3_models_uses_known_list(cli_runner: CliRunner) -> None:
    """Test list_s3_models uses KNOWN_S3_MODELS instead of bucket listing."""
    from bugcam.commands.models import list_s3_models, KNOWN_S3_MODELS

    with patch('bugcam.commands.models.get_s3_model_size', return_value=10000000):
        models = list_s3_models()
        # Should return known models that are accessible
        assert isinstance(models, list)
        assert all(model in KNOWN_S3_MODELS for model in models)


def test_list_available_models_verifies_accessibility(cli_runner: CliRunner) -> None:
    """Test list_available_models verifies each model is accessible via HEAD request."""
    from bugcam.commands.models import list_available_models

    with patch('bugcam.commands.models.get_model_size') as mock_get_size:
        # Only some models are accessible
        mock_get_size.side_effect = lambda name: 10000000 if name == "yolov8s.hef" else None

        models = list_available_models()
        # Should only include accessible models
        assert "yolov8s.hef" in models
        # Inaccessible models should be excluded
        assert all(mock_get_size(m) is not None for m in models)


def test_get_s3_model_size_returns_content_length(cli_runner: CliRunner) -> None:
    """Test get_s3_model_size returns size from Content-Length header."""
    from bugcam.commands.models import get_s3_model_size

    mock_response = MagicMock()
    mock_response.headers.get.return_value = "10485760"  # 10 MB

    with patch('urllib.request.urlopen', return_value=mock_response):
        size = get_s3_model_size("yolov8s.hef")
        assert size == 10485760


def test_get_s3_model_size_returns_none_on_error(cli_runner: CliRunner) -> None:
    """Test get_s3_model_size returns None when request fails."""
    from bugcam.commands.models import get_s3_model_size

    with patch('urllib.request.urlopen', side_effect=Exception("Network error")):
        size = get_s3_model_size("yolov8s.hef")
        assert size is None


def test_get_s3_model_size_uses_head_request(cli_runner: CliRunner) -> None:
    """Test get_s3_model_size uses HEAD request (not GET)."""
    from bugcam.commands.models import get_s3_model_size

    mock_response = MagicMock()
    mock_response.headers.get.return_value = "10485760"

    with patch('urllib.request.Request') as mock_request, \
         patch('urllib.request.urlopen', return_value=mock_response):
        get_s3_model_size("yolov8s.hef")

        # Verify HEAD request was used
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[1].get('method') == 'HEAD'


def test_known_s3_models_constant_exists(cli_runner: CliRunner) -> None:
    """Test KNOWN_S3_MODELS constant is defined and contains expected models."""
    from bugcam.commands.models import KNOWN_S3_MODELS

    assert isinstance(KNOWN_S3_MODELS, list)
    assert len(KNOWN_S3_MODELS) > 0
    assert all(model.endswith('.hef') for model in KNOWN_S3_MODELS)
    # Should include at least the common models
    assert "yolov8s.hef" in KNOWN_S3_MODELS
    assert "yolov8m.hef" in KNOWN_S3_MODELS


def test_models_download_all_uses_known_models(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test 'download all' uses known models list, not bucket listing."""
    with patch('bugcam.commands.models.MODELS_CACHE_DIR', tmp_path), \
         patch('bugcam.commands.models.list_available_models', return_value=['yolov8s.hef', 'yolov8m.hef']) as mock_list, \
         patch('bugcam.commands.models.get_model_size', return_value=10000000), \
         patch('urllib.request.urlopen') as mock_urlopen:
        # Mock successful download
        mock_response = MagicMock()
        mock_response.headers.get.return_value = "10000000"
        mock_response.read.return_value = b""
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = cli_runner.invoke(app, ["models", "download", "all"])

        # Should call list_available_models to get known models
        mock_list.assert_called_once()
