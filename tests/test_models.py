"""Tests for bugcam models command."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error

import pytest
from typer.testing import CliRunner

from bugcam.cli import app
from bugcam.model_bundles import (
    BUNDLE_LABELS_FILENAME,
    BUNDLE_MODEL_FILENAME,
    MODELS_BASE_URL,
    list_remote_bundle_names,
)


def test_models_list_help(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(app, ["models", "list", "--help"])
    assert result.exit_code == 0


def test_models_info_help(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(app, ["models", "info", "--help"])
    assert result.exit_code == 0


def test_models_download_help(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(app, ["models", "download", "--help"])
    assert result.exit_code == 0


def test_models_delete_help(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(app, ["models", "delete", "--help"])
    assert result.exit_code == 0


def test_models_list_shows_bundles(cli_runner: CliRunner, temp_resources_dir: Path, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir), patch(
        "bugcam.commands.models.LOCAL_BUNDLES_DIR", temp_resources_dir
    ):
        result = cli_runner.invoke(app, ["models", "list"])

    assert result.exit_code == 0
    assert "yolov8m" in result.output
    assert "yolov8s" in result.output
    assert "yes" in result.output


def test_models_list_no_models(cli_runner: CliRunner, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    local_dir = tmp_path / "resources"
    cache_dir.mkdir()
    local_dir.mkdir()

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir), patch(
        "bugcam.commands.models.LOCAL_BUNDLES_DIR", local_dir
    ):
        result = cli_runner.invoke(app, ["models", "list"])

    assert result.exit_code == 0
    assert "no model bundles installed" in result.output.lower()


def test_models_info_nonexistent(cli_runner: CliRunner, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    local_dir = tmp_path / "resources"
    cache_dir.mkdir()
    local_dir.mkdir()

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir), patch(
        "bugcam.commands.models.LOCAL_BUNDLES_DIR", local_dir
    ):
        result = cli_runner.invoke(app, ["models", "info", "nonexistent"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_models_info_existing(cli_runner: CliRunner, temp_resources_dir: Path, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir), patch(
        "bugcam.commands.models.LOCAL_BUNDLES_DIR", temp_resources_dir
    ):
        result = cli_runner.invoke(app, ["models", "info", "yolov8m"])

    assert result.exit_code == 0
    assert "yolov8m" in result.output
    assert "model.hef" in result.output
    assert "labels.txt" in result.output


def test_models_download_unknown_model(cli_runner: CliRunner, tmp_path: Path) -> None:
    with patch("bugcam.commands.models.MODELS_CACHE_DIR", tmp_path), patch(
        "bugcam.commands.models.list_available_models", return_value=["yolov8s", "yolov8m"]
    ):
        result = cli_runner.invoke(app, ["models", "download", "nonexistent"])

    assert result.exit_code == 1
    assert "unknown model bundle" in result.output.lower()


def test_models_download_no_arguments(cli_runner: CliRunner, tmp_path: Path) -> None:
    with patch("bugcam.commands.models.MODELS_CACHE_DIR", tmp_path), patch(
        "bugcam.commands.models.list_available_models", return_value=["yolov8s", "yolov8m"]
    ), patch("bugcam.commands.models.get_model_size", return_value=10_000_000):
        result = cli_runner.invoke(app, ["models", "download"])

    assert result.exit_code == 0
    assert "available model bundles" in result.output.lower()
    assert "yolov8s" in result.output
    assert "yolov8m" in result.output


def test_models_download_skips_existing_bundle(
    cli_runner: CliRunner, tmp_path: Path, make_bundle
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    make_bundle(cache_dir, "yolov8s")

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir), patch(
        "bugcam.commands.models.list_available_models", return_value=["yolov8s", "yolov8m"]
    ), patch("bugcam.commands.models.get_model_size", return_value=10_000_000):
        result = cli_runner.invoke(app, ["models", "download", "yolov8s"])

    assert result.exit_code == 0
    assert "already exists" in result.output.lower() or "skipping" in result.output.lower()


def test_models_download_http_404_error(cli_runner: CliRunner, tmp_path: Path) -> None:
    with patch("bugcam.commands.models.MODELS_CACHE_DIR", tmp_path), patch(
        "bugcam.commands.models.list_available_models", return_value=["yolov8s"]
    ), patch("bugcam.commands.models.get_model_size", return_value=10_000_000), patch(
        "urllib.request.urlopen"
    ) as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://test", code=404, msg="Not Found", hdrs={}, fp=None
        )
        result = cli_runner.invoke(app, ["models", "download", "yolov8s"])

    assert result.exit_code == 1
    assert "download failed" in result.output.lower()


def test_models_download_all_uses_available_models(cli_runner: CliRunner, tmp_path: Path) -> None:
    with patch("bugcam.commands.models.MODELS_CACHE_DIR", tmp_path), patch(
        "bugcam.commands.models.list_available_models", return_value=["yolov8s", "yolov8m"]
    ) as mock_list, patch("bugcam.commands.models.get_model_size", return_value=10_000_000), patch(
        "bugcam.commands.models._download_file"
    ) as mock_download:
        result = cli_runner.invoke(app, ["models", "download", "all"])

    assert result.exit_code == 0
    mock_list.assert_called_once()
    assert mock_download.call_count == 4


def test_list_available_models_returns_remote_bundle_names() -> None:
    with patch("bugcam.commands.models.list_remote_bundle_names", return_value=["yolov8s", "yolov8m"]):
        from bugcam.commands.models import list_available_models

        models = list_available_models()

    assert models == ["yolov8s", "yolov8m"]


def test_get_model_size_returns_content_length() -> None:
    from bugcam.commands.models import get_model_size

    mock_response = MagicMock()
    mock_response.headers.get.return_value = "10485760"

    with patch("urllib.request.urlopen", return_value=mock_response):
        size = get_model_size("yolov8s")

    assert size == 10_485_760


def test_get_model_size_returns_none_on_error() -> None:
    from bugcam.commands.models import get_model_size

    with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
        size = get_model_size("yolov8s")

    assert size is None


def test_get_model_size_uses_head_request() -> None:
    from bugcam.commands.models import get_model_size

    mock_response = MagicMock()
    mock_response.headers.get.return_value = "10485760"

    with patch("urllib.request.Request") as mock_request, patch(
        "urllib.request.urlopen", return_value=mock_response
    ):
        get_model_size("yolov8s")

    assert mock_request.call_count == 1
    assert mock_request.call_args.kwargs.get("method") == "HEAD"


def test_get_model_url_constructs_bundle_url() -> None:
    from bugcam.commands.models import get_model_url

    url = get_model_url("yolov8s")
    assert url == f"{MODELS_BASE_URL}/yolov8s/{BUNDLE_MODEL_FILENAME}"


def test_list_remote_bundle_names_parses_xml() -> None:
    mock_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
        <Contents><Key>yolov8s/{BUNDLE_MODEL_FILENAME}</Key></Contents>
        <Contents><Key>yolov8s/{BUNDLE_LABELS_FILENAME}</Key></Contents>
        <Contents><Key>yolov8m/{BUNDLE_MODEL_FILENAME}</Key></Contents>
        <Contents><Key>readme.txt</Key></Contents>
    </ListBucketResult>""".encode("utf-8")

    mock_response = MagicMock()
    mock_response.read.return_value = mock_xml
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False

    with patch("urllib.request.urlopen", return_value=mock_response):
        bundles = list_remote_bundle_names()

    assert bundles == ["yolov8m", "yolov8s"]


def test_models_delete_no_args_shows_bundles(
    cli_runner: CliRunner, tmp_path: Path, make_bundle
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    local_dir = tmp_path / "resources"
    local_dir.mkdir()
    make_bundle(cache_dir, "test_model")

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir), patch(
        "bugcam.commands.models.LOCAL_BUNDLES_DIR", local_dir
    ):
        result = cli_runner.invoke(app, ["models", "delete"])

    assert result.exit_code == 0
    assert "test_model" in result.output


def test_models_delete_nonexistent(cli_runner: CliRunner, tmp_path: Path, make_bundle) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    local_dir = tmp_path / "resources"
    local_dir.mkdir()
    make_bundle(cache_dir, "other_model")

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir), patch(
        "bugcam.commands.models.LOCAL_BUNDLES_DIR", local_dir
    ):
        result = cli_runner.invoke(app, ["models", "delete", "nonexistent"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_models_delete_removes_cache_bundle(
    cli_runner: CliRunner, tmp_path: Path, make_bundle
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    local_dir = tmp_path / "resources"
    local_dir.mkdir()
    bundle_dir = make_bundle(cache_dir, "test_model")

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir), patch(
        "bugcam.commands.models.LOCAL_BUNDLES_DIR", local_dir
    ):
        result = cli_runner.invoke(app, ["models", "delete", "test_model"], input="y\n")

    assert result.exit_code == 0
    assert not bundle_dir.exists()


def test_models_delete_rejects_local_resource_bundle(
    cli_runner: CliRunner, temp_resources_dir: Path, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    with patch("bugcam.commands.models.MODELS_CACHE_DIR", cache_dir), patch(
        "bugcam.commands.models.LOCAL_BUNDLES_DIR", temp_resources_dir
    ):
        result = cli_runner.invoke(app, ["models", "delete", "yolov8m"])

    assert result.exit_code == 1
    assert "cannot delete" in result.output.lower()
