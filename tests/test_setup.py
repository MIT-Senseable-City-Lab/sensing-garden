"""Tests for bugcam setup command."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess
from typer.testing import CliRunner
from bugcam.cli import app


def test_setup_help(cli_runner: CliRunner) -> None:
    """Test setup command help."""
    result = cli_runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0


def test_setup_fails_on_non_linux(cli_runner: CliRunner) -> None:
    """Test setup exits with error on non-Linux platforms."""
    with patch('bugcam.commands.setup.platform.system', return_value='Darwin'):
        result = cli_runner.invoke(app, ["setup"])
        assert result.exit_code == 1
        assert "linux" in result.output.lower() or "raspberry pi" in result.output.lower()


def test_setup_detects_hailo_venv_python(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test get_python_for_detection prefers hailo venv if available."""
    from bugcam.commands.setup import get_python_for_detection

    # Create fake hailo venv
    hailo_python = tmp_path / "hailo-rpi5-examples" / "venv_hailo_rpi_examples" / "bin" / "python"
    hailo_python.parent.mkdir(parents=True)
    hailo_python.touch()

    with patch.object(Path, 'home', return_value=tmp_path):
        python = get_python_for_detection()
        assert python == str(hailo_python)


def test_setup_falls_back_to_system_python(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test get_python_for_detection falls back to /usr/bin/python3 on Linux."""
    from bugcam.commands.setup import get_python_for_detection

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch.object(Path, 'home', return_value=tmp_path):
        # Hailo venv doesn't exist, falls back to system python
        python = get_python_for_detection()
        assert python == "/usr/bin/python3"


def test_setup_uses_sys_executable_fallback(cli_runner: CliRunner) -> None:
    """Test get_python_for_detection uses sys.executable as final fallback."""
    from bugcam.commands.setup import get_python_for_detection
    import sys

    with patch('bugcam.commands.setup.platform.system', return_value='Darwin'), \
         patch('pathlib.Path.exists', return_value=False):
        python = get_python_for_detection()
        assert python == sys.executable


def test_check_import_success(cli_runner: CliRunner) -> None:
    """Test check_import returns True when import succeeds."""
    from bugcam.commands.setup import check_import

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('subprocess.run', return_value=mock_result) as mock_run:
        result = check_import("/usr/bin/python3", "hailo_apps")
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["/usr/bin/python3", "-c", "import hailo_apps"]


def test_check_import_failure(cli_runner: CliRunner) -> None:
    """Test check_import returns False when import fails."""
    from bugcam.commands.setup import check_import

    mock_result = MagicMock()
    mock_result.returncode = 1

    with patch('subprocess.run', return_value=mock_result):
        result = check_import("/usr/bin/python3", "nonexistent_module")
        assert result is False


def test_check_import_handles_exception(cli_runner: CliRunner) -> None:
    """Test check_import returns False on exception."""
    from bugcam.commands.setup import check_import

    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired("test", 10)):
        result = check_import("/usr/bin/python3", "hailo_apps")
        assert result is False


def test_setup_already_installed(cli_runner: CliRunner) -> None:
    """Test setup exits early if hailo_apps is already installed."""
    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch('bugcam.commands.setup.get_python_for_detection', return_value='/usr/bin/python3'), \
         patch('bugcam.commands.setup.check_import', return_value=True):
        result = cli_runner.invoke(app, ["setup"])
        assert result.exit_code == 0
        assert "already installed" in result.output.lower()
        assert "bugcam doctor" in result.output.lower()


def test_setup_installs_with_venv_python(cli_runner: CliRunner) -> None:
    """Test setup uses correct pip flags for hailo venv installation."""
    hailo_venv_python = str(Path.home() / "hailo-rpi5-examples" / "venv_hailo_rpi_examples" / "bin" / "python")

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch('bugcam.commands.setup.get_python_for_detection', return_value=hailo_venv_python), \
         patch('bugcam.commands.setup.check_import', side_effect=[False, True]), \
         patch('subprocess.run', return_value=mock_result) as mock_run:
        result = cli_runner.invoke(app, ["setup"])
        assert result.exit_code == 0

        # Verify correct command was used (no --user or --break-system-packages for venv)
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == hailo_venv_python
        assert "--user" not in call_args
        assert "--break-system-packages" not in call_args
        assert "git+https://github.com/hailo-ai/hailo-apps-infra.git" in call_args


def test_setup_installs_with_system_python_pep668(cli_runner: CliRunner) -> None:
    """Test setup uses --break-system-packages for system Python (PEP 668)."""
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch('bugcam.commands.setup.get_python_for_detection', return_value='/usr/bin/python3'), \
         patch('bugcam.commands.setup.check_import', side_effect=[False, True]), \
         patch('subprocess.run', return_value=mock_result) as mock_run:
        result = cli_runner.invoke(app, ["setup"])
        assert result.exit_code == 0

        # Verify correct command was used (with --user and --break-system-packages)
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == '/usr/bin/python3'
        assert "--user" in call_args
        assert "--break-system-packages" in call_args
        assert "git+https://github.com/hailo-ai/hailo-apps-infra.git" in call_args


def test_setup_installation_failure(cli_runner: CliRunner) -> None:
    """Test setup handles pip installation failure."""
    mock_result = MagicMock()
    mock_result.returncode = 1

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch('bugcam.commands.setup.get_python_for_detection', return_value='/usr/bin/python3'), \
         patch('bugcam.commands.setup.check_import', return_value=False), \
         patch('subprocess.run', return_value=mock_result):
        result = cli_runner.invoke(app, ["setup"])
        assert result.exit_code == 1
        assert "failed" in result.output.lower()


def test_setup_installation_timeout(cli_runner: CliRunner) -> None:
    """Test setup handles installation timeout."""
    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch('bugcam.commands.setup.get_python_for_detection', return_value='/usr/bin/python3'), \
         patch('bugcam.commands.setup.check_import', return_value=False), \
         patch('subprocess.run', side_effect=subprocess.TimeoutExpired("pip", 300)):
        result = cli_runner.invoke(app, ["setup"])
        assert result.exit_code == 1
        assert "timed out" in result.output.lower()


def test_setup_installation_generic_exception(cli_runner: CliRunner) -> None:
    """Test setup handles generic exceptions during installation."""
    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch('bugcam.commands.setup.get_python_for_detection', return_value='/usr/bin/python3'), \
         patch('bugcam.commands.setup.check_import', return_value=False), \
         patch('subprocess.run', side_effect=Exception("Network error")):
        result = cli_runner.invoke(app, ["setup"])
        assert result.exit_code == 1
        assert "error" in result.output.lower()


def test_setup_verification_failure(cli_runner: CliRunner) -> None:
    """Test setup handles verification failure after installation."""
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch('bugcam.commands.setup.get_python_for_detection', return_value='/usr/bin/python3'), \
         patch('bugcam.commands.setup.check_import', side_effect=[False, False]), \
         patch('subprocess.run', return_value=mock_result):
        result = cli_runner.invoke(app, ["setup"])
        assert result.exit_code == 1
        assert "failed" in result.output.lower()
        assert "import hailo_apps" in result.output.lower()


def test_setup_verifies_hailo_apps_import_not_infra(cli_runner: CliRunner) -> None:
    """Test setup verifies 'hailo_apps' import, not 'hailo_apps_infra'."""
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch('bugcam.commands.setup.get_python_for_detection', return_value='/usr/bin/python3'), \
         patch('bugcam.commands.setup.check_import', side_effect=[False, True]) as mock_check, \
         patch('subprocess.run', return_value=mock_result):
        result = cli_runner.invoke(app, ["setup"])
        assert result.exit_code == 0

        # Verify it checks "hailo_apps", not "hailo_apps_infra"
        calls = [call[0][1] for call in mock_check.call_args_list]
        assert "hailo_apps" in calls
        assert "hailo_apps_infra" not in calls
