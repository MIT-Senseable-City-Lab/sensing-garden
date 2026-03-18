"""Tests for bugcam status command."""
import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from bugcam.cli import app


def test_status_help(cli_runner: CliRunner) -> None:
    """Test status command help."""
    result = cli_runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0
    assert "deps" in result.output
    assert "devices" in result.output
    assert "hailo" in result.output
    assert "camera" in result.output


def test_status_deps_help(cli_runner: CliRunner) -> None:
    """Test status deps subcommand help."""
    result = cli_runner.invoke(app, ["status", "deps", "--help"])
    assert result.exit_code == 0


def test_status_devices_help(cli_runner: CliRunner) -> None:
    """Test status devices subcommand help."""
    result = cli_runner.invoke(app, ["status", "devices", "--help"])
    assert result.exit_code == 0


def test_status_hailo_help(cli_runner: CliRunner) -> None:
    """Test status hailo subcommand help."""
    result = cli_runner.invoke(app, ["status", "hailo", "--help"])
    assert result.exit_code == 0


def test_status_camera_help(cli_runner: CliRunner) -> None:
    """Test status camera subcommand help."""
    result = cli_runner.invoke(app, ["status", "camera", "--help"])
    assert result.exit_code == 0


def test_status_sensor_help(cli_runner: CliRunner) -> None:
    """Test status sensor subcommand help."""
    result = cli_runner.invoke(app, ["status", "sensor", "--help"])
    assert result.exit_code == 0


def test_status_models_help(cli_runner: CliRunner) -> None:
    """Test status models subcommand help."""
    result = cli_runner.invoke(app, ["status", "models", "--help"])
    assert result.exit_code == 0


def test_status_jobs_help(cli_runner: CliRunner) -> None:
    """Test status jobs subcommand help."""
    result = cli_runner.invoke(app, ["status", "jobs", "--help"])
    assert result.exit_code == 0


def test_check_hailo_device_success() -> None:
    """Test _check_hailo_device returns True when device found."""
    from bugcam.commands.status import _check_hailo_device

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b"Hailo-8L detected"
    mock_result.stderr = b""

    with patch('subprocess.run', return_value=mock_result):
        ok, detail = _check_hailo_device()
        assert ok is True
        assert "Hailo" in detail


def test_check_hailo_device_not_found() -> None:
    """Test _check_hailo_device returns False when not found."""
    from bugcam.commands.status import _check_hailo_device

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b"Hailo devices not found"
    mock_result.stderr = b""

    with patch('subprocess.run', return_value=mock_result):
        ok, detail = _check_hailo_device()
        assert ok is False


def test_check_hailo_device_missing_cli() -> None:
    """Test _check_hailo_device handles missing hailortcli."""
    from bugcam.commands.status import _check_hailo_device

    with patch('subprocess.run', side_effect=FileNotFoundError()):
        ok, detail = _check_hailo_device()
        assert ok is False
        assert "not installed" in detail


def test_check_camera_success() -> None:
    """Test _check_camera returns True when accessible."""
    from bugcam.commands.status import _check_camera

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = b""

    with patch('subprocess.run', return_value=mock_result):
        ok, detail = _check_camera()
        assert ok is True


def test_check_camera_numpy_error() -> None:
    """Test _check_camera detects numpy incompatibility."""
    from bugcam.commands.status import _check_camera

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = b"numpy.dtype size changed"

    with patch('subprocess.run', return_value=mock_result):
        ok, detail = _check_camera()
        assert ok is False
        assert "NumPy" in detail


def test_check_models_found(tmp_path) -> None:
    """Test _check_models returns True when models exist."""
    from bugcam.commands.status import _check_models

    bundle_dir = tmp_path / "models" / "test"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "model.hef").touch()
    (bundle_dir / "labels.txt").write_text("species-a\n", encoding="utf-8")

    with patch("bugcam.commands.status.get_installed_bundles") as mock_get_installed_bundles:
        mock_get_installed_bundles.return_value = [object()]
        ok, detail = _check_models()
        assert ok is True
        assert "1 installed" in detail


def test_check_models_not_found(tmp_path) -> None:
    """Test _check_models returns False when no models."""
    from bugcam.commands.status import _check_models

    with patch("bugcam.commands.status.get_installed_bundles", return_value=[]):
        ok, detail = _check_models()
        assert ok is False
        assert "None" in detail


def test_status_runs_all_checks(cli_runner: CliRunner) -> None:
    """Test status without subcommand runs all checks."""
    from bugcam.commands import status

    with patch.object(status, '_check_python_import', return_value=True), \
         patch.object(status, '_check_hailo_device', return_value=(True, "OK")), \
         patch.object(status, '_check_camera', return_value=(True, "OK")), \
         patch.object(status, '_check_sensor', return_value=(True, "OK")), \
         patch.object(status, '_check_models', return_value=(True, "1 installed")), \
         patch.object(status, '_check_jobs', return_value=(True, "unprocessed=0, processed=0, upload=0, failed=0")), \
         patch.object(status, '_check_edge26_runtime', return_value=(True, "model=ok, bugspot=ok, labels=ok, requests=ok, hailo_platform=ok")), \
         patch('platform.system', return_value='Linux'):
        result = cli_runner.invoke(app, ["status"])
        assert "system status" in result.output
