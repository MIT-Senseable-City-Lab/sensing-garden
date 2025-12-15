"""Integration tests for bugcam models download functionality.

These tests verify real S3 connectivity and model downloads.
They are marked as integration tests and not run in CI by default.
"""
import pytest
from pathlib import Path
import urllib.request
from typer.testing import CliRunner
from bugcam.cli import app


@pytest.mark.integration
def test_model_download_from_s3(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test that models can actually be downloaded from S3."""
    from unittest.mock import patch

    # Use temp directory for downloads
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    with patch('bugcam.commands.models.MODELS_CACHE_DIR', cache_dir):
        # Download yolov8s (smaller model)
        result = cli_runner.invoke(app, ["models", "download", "yolov8s"])

        # Should succeed
        assert result.exit_code == 0

        # File should exist
        model_file = cache_dir / "yolov8s.hef"
        assert model_file.exists()

        # File should be the expected size (approximately 10-11 MB)
        file_size = model_file.stat().st_size
        assert file_size > 9_000_000  # At least 9 MB
        assert file_size < 15_000_000  # Less than 15 MB

        # File should be a valid .hef file (not empty, has binary content)
        with open(model_file, 'rb') as f:
            header = f.read(16)
            assert len(header) == 16
            assert header != b'\x00' * 16  # Not all zeros


@pytest.mark.integration
def test_s3_both_models_accessible() -> None:
    """Verify both S3 models (yolov8s and yolov8m) are publicly accessible."""
    models = [
        ("yolov8s.hef", 9_000_000, 15_000_000),  # ~10.1 MB
        ("yolov8m.hef", 25_000_000, 35_000_000),  # ~29.1 MB
    ]

    for model_name, min_size, max_size in models:
        url = f"https://scl-sensing-garden-models.s3.amazonaws.com/{model_name}"

        # Check HEAD request (availability)
        req = urllib.request.Request(url, method='HEAD')
        response = urllib.request.urlopen(req)
        assert response.status == 200

        # Verify content length is within expected range
        content_length = int(response.headers.get('Content-Length', 0))
        assert content_length > min_size, f"{model_name} too small: {content_length}"
        assert content_length < max_size, f"{model_name} too large: {content_length}"


@pytest.mark.integration
def test_download_invalid_model_fails(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test that downloading non-existent model fails gracefully."""
    from unittest.mock import patch

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    with patch('bugcam.commands.models.MODELS_CACHE_DIR', cache_dir):
        result = cli_runner.invoke(app, ["models", "download", "nonexistent_model"])

        # Should fail
        assert result.exit_code == 1

        # Should show error message
        assert "unknown" in result.output.lower() or "error" in result.output.lower()


@pytest.mark.integration
def test_download_multiple_models_sequentially(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test downloading multiple models sequentially."""
    from unittest.mock import patch

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    with patch('bugcam.commands.models.MODELS_CACHE_DIR', cache_dir):
        # Download yolov8s
        result1 = cli_runner.invoke(app, ["models", "download", "yolov8s"])
        assert result1.exit_code == 0

        # Download yolov8m
        result2 = cli_runner.invoke(app, ["models", "download", "yolov8m"])
        assert result2.exit_code == 0

        # Both model files should exist
        assert (cache_dir / "yolov8s.hef").exists()
        assert (cache_dir / "yolov8m.hef").exists()

        # Both should have valid sizes
        yolov8s_size = (cache_dir / "yolov8s.hef").stat().st_size
        yolov8m_size = (cache_dir / "yolov8m.hef").stat().st_size

        assert yolov8s_size > 9_000_000
        assert yolov8m_size > 25_000_000


@pytest.mark.integration
def test_download_skip_existing(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test that download skips files that already exist."""
    from unittest.mock import patch

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    with patch('bugcam.commands.models.MODELS_CACHE_DIR', cache_dir):
        # First download
        result1 = cli_runner.invoke(app, ["models", "download", "yolov8s"])
        assert result1.exit_code == 0

        # Second download should skip
        result2 = cli_runner.invoke(app, ["models", "download", "yolov8s"])
        assert result2.exit_code == 0
        assert "skip" in result2.output.lower() or "already exists" in result2.output.lower()
