"""Tests for bugcam preview command."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from bugcam.cli import app


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
