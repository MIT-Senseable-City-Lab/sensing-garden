"""Tests for bugcam autostart command."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from bugcam.cli import app
from bugcam.commands.autostart import _validate_model_name


class TestModelNameValidation:
    """SECURITY-CRITICAL: Tests for model name validation to prevent command injection."""

    def test_valid_model_names_accepted(self) -> None:
        """Test that valid model names are accepted."""
        valid_names = [
            "yolov8s.hef",
            "yolov8m.hef",
            "custom_model.hef",
            "models/yolov8s.hef",
        ]
        for name in valid_names:
            assert _validate_model_name(name), f"Valid model name rejected: {name}"

    def test_command_injection_rejected(self) -> None:
        """Test that command injection attempts are rejected."""
        assert not _validate_model_name("; rm -rf /"), "Command injection with semicolon not rejected"

    def test_pipe_injection_rejected(self) -> None:
        """Test that pipe injection attempts are rejected."""
        assert not _validate_model_name("| cat /etc/passwd"), "Pipe injection not rejected"

    def test_command_substitution_dollar_rejected(self) -> None:
        """Test that command substitution with $() is rejected."""
        assert not _validate_model_name("$(whoami)"), "Command substitution with $() not rejected"

    def test_command_substitution_backtick_rejected(self) -> None:
        """Test that command substitution with backticks is rejected."""
        assert not _validate_model_name("`id`"), "Command substitution with backticks not rejected"

    def test_redirect_injection_rejected(self) -> None:
        """Test that redirect injection is rejected."""
        assert not _validate_model_name("> /tmp/out"), "Redirect injection not rejected"

    def test_space_in_name_rejected(self) -> None:
        """Test that spaces in model names are rejected."""
        assert not _validate_model_name("model name"), "Space in model name not rejected"

    def test_newline_in_name_rejected(self) -> None:
        """Test that newlines in model names are rejected."""
        assert not _validate_model_name("model\nname"), "Newline in model name not rejected"

    def test_empty_string_rejected(self) -> None:
        """Test that empty string is rejected."""
        assert not _validate_model_name(""), "Empty string not rejected"


class TestAutostart:
    """Tests for autostart commands."""

    def test_autostart_enable_help(self, cli_runner):
        """Test autostart enable help."""
        result = cli_runner.invoke(app, ["autostart", "enable", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output or "model" in result.output.lower()

    def test_autostart_disable_help(self, cli_runner):
        """Test autostart disable help."""
        result = cli_runner.invoke(app, ["autostart", "disable", "--help"])
        assert result.exit_code == 0

    def test_autostart_status_help(self, cli_runner):
        """Test autostart status help."""
        result = cli_runner.invoke(app, ["autostart", "status", "--help"])
        assert result.exit_code == 0

    def test_autostart_logs_help(self, cli_runner):
        """Test autostart logs help."""
        result = cli_runner.invoke(app, ["autostart", "logs", "--help"])
        assert result.exit_code == 0
        assert "--follow" in result.output or "-f" in result.output
        assert "--lines" in result.output or "-n" in result.output

    @patch('bugcam.commands.autostart.SYSTEMD_SERVICE_PATH')
    def test_autostart_status_not_installed(self, mock_path, cli_runner):
        """Test status when service not installed."""
        mock_path.exists.return_value = False

        result = cli_runner.invoke(app, ["autostart", "status"])
        # Should indicate service not installed with exit code 0
        assert result.exit_code == 0
        assert "not installed" in result.output.lower()

    @patch('bugcam.commands.autostart.SYSTEMD_SERVICE_PATH')
    def test_autostart_disable_not_installed(self, mock_path, cli_runner):
        """Test disable when service not installed."""
        mock_path.exists.return_value = False

        result = cli_runner.invoke(app, ["autostart", "disable"])
        # Should handle gracefully with exit code 0
        assert result.exit_code == 0
        assert "not installed" in result.output.lower()
