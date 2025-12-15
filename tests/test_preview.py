"""Tests for bugcam preview command."""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from bugcam.cli import app
from bugcam.commands.preview import get_python_for_detection


class TestPreview:
    """Tests for preview command."""

    def test_preview_help(self, cli_runner):
        """Test preview help text."""
        result = cli_runner.invoke(app, ["preview", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output or "-m" in result.output
        assert "--duration" in result.output or "-d" in result.output

    @patch('bugcam.commands.preview.subprocess.Popen')
    @patch('pathlib.Path.exists')
    def test_preview_calls_subprocess_with_model(self, mock_exists, mock_popen, cli_runner):
        """Test preview calls subprocess with correct args when model exists."""
        mock_exists.return_value = True
        mock_process = MagicMock()
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        result = cli_runner.invoke(app, ["preview", "--model", "/fake/model.hef"])

        # Verify subprocess was called
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert "--input" in call_args
        assert "rpi" in call_args
        assert "--hef-path" in call_args
        assert "/fake/model.hef" in call_args

    def test_preview_missing_detection_script(self, cli_runner):
        """Test preview handles missing detection script."""
        with patch('pathlib.Path.exists', return_value=False):
            result = cli_runner.invoke(app, ["preview"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower() or "error" in result.output.lower()


class TestPythonInterpreterSelection:
    """Tests for Python interpreter selection (RPi5 vs Mac)."""

    @patch('bugcam.commands.preview.platform.system', return_value='Linux')
    def test_get_python_returns_system_python_on_linux(self, mock_system: MagicMock, tmp_path: Path) -> None:
        """On Linux (RPi5) without hailo venv, should return /usr/bin/python3."""
        with patch.object(Path, 'home', return_value=tmp_path):
            result = get_python_for_detection()
            assert result == "/usr/bin/python3"

    @patch('bugcam.commands.preview.platform.system', return_value='Linux')
    def test_get_python_uses_hailo_venv_when_available(self, mock_system: MagicMock, tmp_path: Path) -> None:
        """On Linux with hailo venv, should use hailo venv Python."""
        hailo_python = tmp_path / "hailo-rpi5-examples" / "venv_hailo_rpi_examples" / "bin" / "python"
        hailo_python.parent.mkdir(parents=True)
        hailo_python.touch()

        with patch.object(Path, 'home', return_value=tmp_path):
            result = get_python_for_detection()
            assert result == str(hailo_python)

    @patch('bugcam.commands.preview.platform.system', return_value='Darwin')
    def test_get_python_returns_sys_executable_on_mac(self, mock_system: MagicMock) -> None:
        """On Mac (Darwin), should return sys.executable."""
        result = get_python_for_detection()
        assert result == sys.executable

    @patch('bugcam.commands.preview.preflight_check', return_value=True)
    @patch('bugcam.commands.preview.platform.system', return_value='Linux')
    @patch('bugcam.commands.preview.subprocess.Popen')
    def test_preview_uses_system_python_on_rpi(
        self, mock_popen: MagicMock, mock_system: MagicMock,
        mock_preflight: MagicMock, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """On RPi5 (Linux) without hailo venv, preview should use /usr/bin/python3."""
        mock_process = MagicMock()
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        with patch.object(Path, 'home', return_value=tmp_path):
            result = cli_runner.invoke(app, ["preview", "--model", "/fake/model.hef"])

        # Verify subprocess was called with system Python
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert call_args[0] == "/usr/bin/python3", f"Expected /usr/bin/python3 but got {call_args[0]}"
