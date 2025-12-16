"""Tests for bugcam check command."""
import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from bugcam.cli import app


def test_check_help(cli_runner: CliRunner) -> None:
    """Test check command help."""
    result = cli_runner.invoke(app, ["check", "--help"])
    assert result.exit_code == 0
    assert "hailo" in result.output
    assert "camera" in result.output
    assert "sensor" in result.output


def test_check_hailo_help(cli_runner: CliRunner) -> None:
    """Test check hailo subcommand help."""
    result = cli_runner.invoke(app, ["check", "hailo", "--help"])
    assert result.exit_code == 0


def test_check_hailo_success(cli_runner: CliRunner) -> None:
    """Test check hailo succeeds when device is found."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b"Hailo-8L (M.2) detected"
    mock_result.stderr = b""

    with patch('subprocess.run', return_value=mock_result):
        result = cli_runner.invoke(app, ["check", "hailo"])
        assert result.exit_code == 0
        assert "Hailo" in result.output


def test_check_hailo_not_found(cli_runner: CliRunner) -> None:
    """Test check hailo fails when no device found."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b"Hailo devices not found"
    mock_result.stderr = b""

    with patch('subprocess.run', return_value=mock_result):
        result = cli_runner.invoke(app, ["check", "hailo"])
        assert result.exit_code == 1
        assert "No Hailo device found" in result.output


def test_check_hailo_hailortcli_missing(cli_runner: CliRunner) -> None:
    """Test check hailo fails when hailortcli not installed."""
    with patch('subprocess.run', side_effect=FileNotFoundError()):
        result = cli_runner.invoke(app, ["check", "hailo"])
        assert result.exit_code == 1
        assert "hailortcli not found" in result.output


def test_check_camera_help(cli_runner: CliRunner) -> None:
    """Test check camera subcommand help."""
    result = cli_runner.invoke(app, ["check", "camera", "--help"])
    assert result.exit_code == 0


def test_check_camera_success(cli_runner: CliRunner) -> None:
    """Test check camera succeeds when camera accessible."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = b""

    with patch('subprocess.run', return_value=mock_result):
        result = cli_runner.invoke(app, ["check", "camera"])
        assert result.exit_code == 0
        assert "Camera accessible" in result.output


def test_check_camera_numpy_incompatibility(cli_runner: CliRunner) -> None:
    """Test check camera detects numpy binary incompatibility."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = b"numpy.dtype size changed, may indicate binary incompatibility"

    with patch('subprocess.run', return_value=mock_result):
        result = cli_runner.invoke(app, ["check", "camera"])
        assert result.exit_code == 1
        assert "NumPy binary incompatibility" in result.output


def test_check_sensor_help(cli_runner: CliRunner) -> None:
    """Test check sensor subcommand help."""
    result = cli_runner.invoke(app, ["check", "sensor", "--help"])
    assert result.exit_code == 0


def test_check_all_help(cli_runner: CliRunner) -> None:
    """Test check all subcommand help."""
    result = cli_runner.invoke(app, ["check", "all", "--help"])
    assert result.exit_code == 0


def test_check_all_runs_all_checks(cli_runner: CliRunner) -> None:
    """Test check all runs hailo, camera, and sensor checks."""
    from bugcam.commands import check

    with patch.object(check, 'check_hailo', return_value=True) as mock_hailo, \
         patch.object(check, 'check_camera', return_value=True) as mock_camera, \
         patch.object(check, 'check_sensor', return_value=True) as mock_sensor:
        result = cli_runner.invoke(app, ["check", "all"])
        assert result.exit_code == 0
        mock_hailo.assert_called_once()
        mock_camera.assert_called_once()
        mock_sensor.assert_called_once()


def test_check_all_fails_if_hailo_fails(cli_runner: CliRunner) -> None:
    """Test check all fails if hailo check fails."""
    from bugcam.commands import check

    with patch.object(check, 'check_hailo', return_value=False), \
         patch.object(check, 'check_camera', return_value=True), \
         patch.object(check, 'check_sensor', return_value=True):
        result = cli_runner.invoke(app, ["check", "all"])
        assert result.exit_code == 1
