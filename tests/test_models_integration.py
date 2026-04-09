"""Integration tests for bugcam model bundle downloads."""
from pathlib import Path
import urllib.request

import pytest
from typer.testing import CliRunner

from bugcam.cli import app
from bugcam.model_bundles import (
    BUNDLE_LABELS_FILENAME,
    BUNDLE_MODEL_FILENAME,
    get_remote_bundle_file_url,
    list_remote_bundle_names,
)


def _require_remote_bundles() -> list[str]:
    bundles = list_remote_bundle_names()
    if not bundles:
        pytest.skip("Remote S3 bucket has not been migrated to bundle layout yet")
    return bundles


@pytest.mark.integration
def test_model_download_from_s3(cli_runner: CliRunner, tmp_path: Path) -> None:
    from unittest.mock import patch

    bundles = _require_remote_bundles()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    bundle_name = bundles[0]

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir):
        result = cli_runner.invoke(app, ["models", "download", bundle_name])

    assert result.exit_code == 0
    assert (cache_dir / bundle_name / BUNDLE_MODEL_FILENAME).exists()
    assert (cache_dir / bundle_name / BUNDLE_LABELS_FILENAME).exists()


@pytest.mark.integration
def test_s3_bundle_files_accessible() -> None:
    bundles = _require_remote_bundles()
    bundle_name = bundles[0]

    for filename in (BUNDLE_MODEL_FILENAME, BUNDLE_LABELS_FILENAME):
        req = urllib.request.Request(get_remote_bundle_file_url(bundle_name, filename), method="HEAD")
        response = urllib.request.urlopen(req)
        assert response.status == 200


@pytest.mark.integration
def test_download_invalid_model_fails(cli_runner: CliRunner, tmp_path: Path) -> None:
    from unittest.mock import patch

    _require_remote_bundles()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir):
        result = cli_runner.invoke(app, ["models", "download", "nonexistent-model"])

    assert result.exit_code == 1
    assert "unknown" in result.output.lower() or "error" in result.output.lower()


@pytest.mark.integration
def test_download_multiple_models_sequentially(cli_runner: CliRunner, tmp_path: Path) -> None:
    from unittest.mock import patch

    bundles = _require_remote_bundles()
    if len(bundles) < 2:
        pytest.skip("Remote bundle bucket exposes fewer than two bundles")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir):
        result1 = cli_runner.invoke(app, ["models", "download", bundles[0]])
        result2 = cli_runner.invoke(app, ["models", "download", bundles[1]])

    assert result1.exit_code == 0
    assert result2.exit_code == 0
    assert (cache_dir / bundles[0] / BUNDLE_MODEL_FILENAME).exists()
    assert (cache_dir / bundles[1] / BUNDLE_MODEL_FILENAME).exists()


@pytest.mark.integration
def test_download_skip_existing(cli_runner: CliRunner, tmp_path: Path) -> None:
    from unittest.mock import patch

    bundles = _require_remote_bundles()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir):
        first = cli_runner.invoke(app, ["models", "download", bundles[0]])
        second = cli_runner.invoke(app, ["models", "download", bundles[0]])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "skip" in second.output.lower() or "already exists" in second.output.lower()
