"""Tests for bugcam doctor command."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess
from typer.testing import CliRunner
from bugcam.cli import app


def test_doctor_help(cli_runner: CliRunner) -> None:
    """Test doctor command help."""
    result = cli_runner.invoke(app, ["doctor", "--help"])
    assert result.exit_code == 0


def test_doctor_get_python_prefers_hailo_venv(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test get_python_for_detection prefers hailo venv."""
    from bugcam.commands.doctor import get_python_for_detection

    # Create fake hailo venv
    hailo_python = tmp_path / "hailo-rpi5-examples" / "venv_hailo_rpi_examples" / "bin" / "python"
    hailo_python.parent.mkdir(parents=True)
    hailo_python.touch()

    with patch.object(Path, 'home', return_value=tmp_path):
        python = get_python_for_detection()
        assert python == str(hailo_python)


def test_doctor_get_python_falls_back_to_system(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test get_python_for_detection falls back to system Python."""
    from bugcam.commands.doctor import get_python_for_detection

    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch.object(Path, 'home', return_value=tmp_path):
        # Hailo venv doesn't exist, falls back to system python
        python = get_python_for_detection()
        assert python == "/usr/bin/python3"


def test_doctor_check_import_success(cli_runner: CliRunner) -> None:
    """Test check_system_python_import returns True when import succeeds."""
    from bugcam.commands.doctor import check_system_python_import

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.get_python_for_detection', return_value='/usr/bin/python3'), \
         patch('subprocess.run', return_value=mock_result) as mock_run:
        result = check_system_python_import("hailo_apps")
        assert result is True

        # Verify correct import command
        args = mock_run.call_args[0][0]
        assert args == ["/usr/bin/python3", "-c", "import hailo_apps"]


def test_doctor_check_import_failure(cli_runner: CliRunner) -> None:
    """Test check_system_python_import returns False when import fails."""
    from bugcam.commands.doctor import check_system_python_import

    mock_result = MagicMock()
    mock_result.returncode = 1

    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.get_python_for_detection', return_value='/usr/bin/python3'), \
         patch('subprocess.run', return_value=mock_result):
        result = check_system_python_import("nonexistent_module")
        assert result is False


def test_doctor_check_import_handles_exception(cli_runner: CliRunner) -> None:
    """Test check_system_python_import handles exceptions."""
    from bugcam.commands.doctor import check_system_python_import

    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.get_python_for_detection', return_value='/usr/bin/python3'), \
         patch('subprocess.run', side_effect=subprocess.TimeoutExpired("test", 10)):
        result = check_system_python_import("hailo_apps")
        assert result is False


def test_doctor_check_import_returns_false_on_non_linux(cli_runner: CliRunner) -> None:
    """Test check_system_python_import returns False on non-Linux platforms."""
    from bugcam.commands.doctor import check_system_python_import

    with patch('bugcam.commands.doctor.platform.system', return_value='Darwin'):
        result = check_system_python_import("hailo_apps")
        assert result is False


def test_doctor_checks_hailo_apps_not_hailo_apps_infra(cli_runner: CliRunner) -> None:
    """Test doctor checks 'hailo_apps' import, not 'hailo_apps_infra'."""
    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.check_system_python_import', return_value=True) as mock_check, \
         patch('pathlib.Path.exists', return_value=False):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0

        # Verify it checks "hailo_apps", not "hailo_apps_infra"
        calls = [call[0][0] for call in mock_check.call_args_list]
        assert "hailo_apps" in calls
        assert "hailo_apps_infra" not in calls


def test_doctor_shows_all_dependencies(cli_runner: CliRunner) -> None:
    """Test doctor checks all required dependencies."""
    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.check_system_python_import', return_value=True), \
         patch('pathlib.Path.exists', return_value=False):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0

        # Should check these dependencies
        assert "gi" in result.output
        assert "hailo" in result.output
        assert "hailo_apps" in result.output
        assert "numpy" in result.output
        assert "cv2" in result.output


def test_doctor_shows_ok_for_satisfied_dependencies(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test doctor shows OK status for satisfied dependencies."""
    # Create a fake model file
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "yolov8s.hef").write_bytes(b"fake model")

    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.check_system_python_import', return_value=True), \
         patch('bugcam.commands.doctor.Path.home', return_value=tmp_path):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "OK" in result.output


def test_doctor_shows_missing_for_unsatisfied_dependencies(cli_runner: CliRunner) -> None:
    """Test doctor shows MISSING status for unsatisfied dependencies."""
    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.check_system_python_import', return_value=False), \
         patch('pathlib.Path.exists', return_value=False):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "MISSING" in result.output


def test_doctor_shows_install_commands_for_missing_deps(cli_runner: CliRunner) -> None:
    """Test doctor shows installation commands for missing dependencies."""
    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.check_system_python_import', return_value=False), \
         patch('pathlib.Path.exists', return_value=False):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0

        # Should show install commands
        assert "sudo apt install" in result.output or "bugcam setup" in result.output


def test_doctor_checks_for_model_files(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test doctor checks for .hef model files."""
    # Create models directory with a model file
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "yolov8s.hef").write_bytes(b"fake model")

    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.check_system_python_import', return_value=True), \
         patch('bugcam.commands.doctor.Path.home', return_value=tmp_path):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "model" in result.output.lower()
        assert "OK" in result.output


def test_doctor_shows_missing_when_no_model_files(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test doctor shows MISSING when no .hef files exist."""
    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.check_system_python_import', return_value=True), \
         patch('bugcam.commands.doctor.Path.home', return_value=tmp_path):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "MISSING" in result.output


def test_doctor_shows_count_of_model_files(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test doctor shows count of available model files."""
    # Create multiple model files
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "yolov8s.hef").write_bytes(b"fake model 1")
    (models_dir / "yolov8m.hef").write_bytes(b"fake model 2")

    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.check_system_python_import', return_value=True), \
         patch('bugcam.commands.doctor.Path.home', return_value=tmp_path):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "2 found" in result.output or "2" in result.output


def test_doctor_shows_platform_warning_on_non_linux(cli_runner: CliRunner) -> None:
    """Test doctor shows platform warning on non-Linux systems."""
    with patch('bugcam.commands.doctor.platform.system', return_value='Darwin'):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "linux" in result.output.lower() or "raspberry pi" in result.output.lower()


def test_doctor_skips_checks_on_non_linux(cli_runner: CliRunner) -> None:
    """Test doctor marks dependencies as 'skip' on non-Linux platforms."""
    with patch('bugcam.commands.doctor.platform.system', return_value='Darwin'), \
         patch('pathlib.Path.exists', return_value=False):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "skip" in result.output.lower() or "linux only" in result.output.lower()


def test_doctor_shows_success_message_when_all_ok(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test doctor shows success message when all dependencies are satisfied."""
    # Create a fake model file
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "yolov8s.hef").write_bytes(b"fake model")

    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.check_system_python_import', return_value=True), \
         patch('bugcam.commands.doctor.Path.home', return_value=tmp_path):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "all dependencies satisfied" in result.output.lower() or "ok" in result.output.lower()


def test_doctor_shows_warning_message_when_missing(cli_runner: CliRunner) -> None:
    """Test doctor shows warning message when dependencies are missing."""
    with patch('bugcam.commands.doctor.platform.system', return_value='Linux'), \
         patch('bugcam.commands.doctor.check_system_python_import', return_value=False), \
         patch('pathlib.Path.exists', return_value=False):
        result = cli_runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "missing" in result.output.lower()
