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


def test_setup_clones_repo_if_not_exists(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test setup clones hailo-rpi5-examples if directory doesn't exist."""
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch.object(Path, 'home', return_value=tmp_path), \
         patch('subprocess.run', return_value=mock_result) as mock_run:
        result = cli_runner.invoke(app, ["setup"])

        # Should have called git clone
        calls = [call[0][0] for call in mock_run.call_args_list]
        git_clone_call = next((c for c in calls if c[0] == "git" and c[1] == "clone"), None)
        assert git_clone_call is not None
        assert "hailo-ai/hailo-rpi5-examples.git" in git_clone_call[2]


def test_setup_skips_clone_if_exists(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test setup skips clone if hailo-rpi5-examples already exists."""
    # Create fake hailo-rpi5-examples directory with required scripts
    hailo_dir = tmp_path / "hailo-rpi5-examples"
    hailo_dir.mkdir()
    (hailo_dir / "install.sh").touch()
    (hailo_dir / "compile_postprocess.sh").touch()
    (hailo_dir / "setup_env.sh").touch()

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch.object(Path, 'home', return_value=tmp_path), \
         patch('subprocess.run', return_value=mock_result) as mock_run, \
         patch('bugcam.commands.setup.check_import', return_value=True):
        result = cli_runner.invoke(app, ["setup"])

        # Should not have called git clone
        calls = [call[0][0] for call in mock_run.call_args_list]
        git_clone_calls = [c for c in calls if isinstance(c, list) and len(c) > 1 and c[0] == "git" and c[1] == "clone"]
        assert len(git_clone_calls) == 0
        assert "Found hailo-rpi5-examples" in result.output


def test_setup_runs_install_script(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test setup runs install.sh script."""
    hailo_dir = tmp_path / "hailo-rpi5-examples"
    hailo_dir.mkdir()
    (hailo_dir / "install.sh").touch()
    (hailo_dir / "compile_postprocess.sh").touch()
    (hailo_dir / "setup_env.sh").touch()

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch.object(Path, 'home', return_value=tmp_path), \
         patch('subprocess.run', return_value=mock_result) as mock_run, \
         patch('bugcam.commands.setup.check_import', return_value=True):
        result = cli_runner.invoke(app, ["setup"])

        # Should have called ./install.sh
        calls = [call[0][0] for call in mock_run.call_args_list]
        install_call = next((c for c in calls if c == ["./install.sh"]), None)
        assert install_call is not None


def test_setup_compiles_postprocess(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test setup runs compile_postprocess.sh script."""
    hailo_dir = tmp_path / "hailo-rpi5-examples"
    hailo_dir.mkdir()
    (hailo_dir / "install.sh").touch()
    (hailo_dir / "compile_postprocess.sh").touch()
    (hailo_dir / "setup_env.sh").touch()

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch.object(Path, 'home', return_value=tmp_path), \
         patch('subprocess.run', return_value=mock_result) as mock_run, \
         patch('bugcam.commands.setup.check_import', return_value=True):
        result = cli_runner.invoke(app, ["setup"])

        # Should have called bash to run compile script
        calls = [call[0][0] for call in mock_run.call_args_list]
        compile_call = next((c for c in calls if c[0] == "bash" and "-c" in c), None)
        assert compile_call is not None
        assert "compile_postprocess.sh" in compile_call[2]


def test_setup_install_script_failure(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test setup handles install.sh failure."""
    hailo_dir = tmp_path / "hailo-rpi5-examples"
    hailo_dir.mkdir()
    (hailo_dir / "install.sh").touch()
    (hailo_dir / "compile_postprocess.sh").touch()
    (hailo_dir / "setup_env.sh").touch()

    mock_success = MagicMock()
    mock_success.returncode = 0
    mock_failure = MagicMock()
    mock_failure.returncode = 1

    def run_side_effect(cmd, **kwargs):
        if cmd == ["./install.sh"]:
            return mock_failure
        return mock_success

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch.object(Path, 'home', return_value=tmp_path), \
         patch('subprocess.run', side_effect=run_side_effect):
        result = cli_runner.invoke(app, ["setup"])
        assert result.exit_code == 1
        assert "failed" in result.output.lower()


def test_setup_verifies_hailo_apps(cli_runner: CliRunner, tmp_path: Path) -> None:
    """Test setup verifies hailo_apps installation at the end."""
    hailo_dir = tmp_path / "hailo-rpi5-examples"
    hailo_dir.mkdir()
    (hailo_dir / "install.sh").touch()
    (hailo_dir / "compile_postprocess.sh").touch()
    (hailo_dir / "setup_env.sh").touch()

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('bugcam.commands.setup.platform.system', return_value='Linux'), \
         patch.object(Path, 'home', return_value=tmp_path), \
         patch('subprocess.run', return_value=mock_result), \
         patch('bugcam.commands.setup.check_import', return_value=True) as mock_check:
        result = cli_runner.invoke(app, ["setup"])
        assert result.exit_code == 0
        assert "hailo_apps: OK" in result.output

        # Verify it checks hailo_apps import
        mock_check.assert_called_with(mock_check.call_args[0][0], "hailo_apps")
