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
         patch('bugcam.commands.models.list_available_models', return_value=['yolov8s.hef']), \
         patch('bugcam.commands.models.get_model_size', return_value=10000000), \
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
         patch('bugcam.commands.models.list_available_models', return_value=['yolov8s.hef', 'yolov8m.hef']):
        result = cli_runner.invoke(app, ["models", "download", "nonexistent.hef"])
        assert result.exit_code == 1
        assert "unknown" in result.output.lower()


def test_models_download_no_arguments(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test download without arguments shows available models help text."""
    with patch('bugcam.commands.models.MODELS_CACHE_DIR', tmp_path), \
         patch('bugcam.commands.models.list_available_models', return_value=['yolov8s.hef', 'yolov8m.hef']), \
         patch('bugcam.commands.models.get_model_size', return_value=10000000):
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
         patch('bugcam.commands.models.list_available_models', return_value=['yolov8s.hef', 'yolov8m.hef']), \
         patch('bugcam.commands.models.get_model_size', return_value=10000000):
        result = cli_runner.invoke(app, ["models", "download", "yolov8s"])
        assert result.exit_code == 0
        assert "skipping" in result.output.lower() or "already exists" in result.output.lower()


def test_list_s3_models_queries_bucket(cli_runner: CliRunner) -> None:
    """Test list_s3_models dynamically queries S3 bucket."""
    from bugcam.commands.models import list_s3_models

    with patch('bugcam.commands.models.list_s3_bucket_models', return_value=['yolov8s.hef', 'yolov8m.hef']):
        models = list_s3_models()
        # Should return models from bucket listing
        assert isinstance(models, list)
        assert 'yolov8s.hef' in models
        assert 'yolov8m.hef' in models


def test_list_available_models_returns_bucket_contents(cli_runner: CliRunner) -> None:
    """Test list_available_models returns S3 bucket contents."""
    from bugcam.commands.models import list_available_models

    with patch('bugcam.commands.models.list_s3_bucket_models', return_value=['yolov8s.hef', 'yolov8m.hef']):
        models = list_available_models()
        # Should return models from bucket
        assert isinstance(models, list)
        assert 'yolov8s.hef' in models
        assert 'yolov8m.hef' in models


def test_get_model_size_returns_content_length(cli_runner: CliRunner) -> None:
    """Test get_model_size returns size from Content-Length header."""
    from bugcam.commands.models import get_model_size

    mock_response = MagicMock()
    mock_response.headers.get.return_value = "10485760"  # 10 MB

    with patch('urllib.request.urlopen', return_value=mock_response):
        size = get_model_size("yolov8s.hef")
        assert size == 10485760


def test_get_model_size_returns_none_on_error(cli_runner: CliRunner) -> None:
    """Test get_model_size returns None when request fails."""
    from bugcam.commands.models import get_model_size

    with patch('urllib.request.urlopen', side_effect=Exception("Network error")):
        size = get_model_size("yolov8s.hef")
        assert size is None


def test_get_model_size_uses_head_request(cli_runner: CliRunner) -> None:
    """Test get_model_size uses HEAD request (not GET)."""
    from bugcam.commands.models import get_model_size

    mock_response = MagicMock()
    mock_response.headers.get.return_value = "10485760"

    with patch('urllib.request.Request') as mock_request, \
         patch('urllib.request.urlopen', return_value=mock_response):
        get_model_size("yolov8s.hef")

        # Verify HEAD request was used
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[1].get('method') == 'HEAD'


def test_get_model_url_constructs_s3_url(cli_runner: CliRunner) -> None:
    """Test get_model_url constructs correct S3 URL."""
    from bugcam.commands.models import get_model_url, MODELS_BASE_URL

    url = get_model_url("yolov8s.hef")
    assert url == f"{MODELS_BASE_URL}/yolov8s.hef"


def test_models_download_all_uses_available_models(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test 'download all' uses dynamically fetched available models."""
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

        # Should call list_available_models to get models from S3
        mock_list.assert_called_once()


def test_list_s3_bucket_models_parses_xml(cli_runner: CliRunner) -> None:
    """Test list_s3_bucket_models parses S3 bucket XML listing."""
    from bugcam.commands.models import list_s3_bucket_models

    # Mock S3 XML response
    mock_xml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
        <Contents><Key>yolov8s.hef</Key><Size>10602702</Size></Contents>
        <Contents><Key>yolov8m.hef</Key><Size>30516142</Size></Contents>
        <Contents><Key>readme.txt</Key><Size>100</Size></Contents>
    </ListBucketResult>'''

    mock_response = MagicMock()
    mock_response.read.return_value = mock_xml
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch('urllib.request.urlopen', return_value=mock_response):
        models = list_s3_bucket_models()
        # Should include .hef files only
        assert 'yolov8s.hef' in models
        assert 'yolov8m.hef' in models
        # Should not include non-.hef files
        assert 'readme.txt' not in models
