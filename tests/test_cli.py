"""Tests for the main bugcam CLI structure."""
import pytest
from typer.testing import CliRunner
from bugcam.cli import app


def test_main_help(cli_runner):
    """Test that main help shows correct info."""
    result = cli_runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "bugcam" in result.output.lower() or "CLI" in result.output


def test_models_subcommand_help(cli_runner):
    """Test models subcommand is accessible."""
    result = cli_runner.invoke(app, ["models", "--help"])
    assert result.exit_code == 0
    assert "model" in result.output.lower()


def test_detect_subcommand_help(cli_runner):
    """Test detect subcommand is accessible."""
    result = cli_runner.invoke(app, ["detect", "--help"])
    assert result.exit_code == 0


def test_preview_subcommand_help(cli_runner):
    """Test preview subcommand is accessible."""
    result = cli_runner.invoke(app, ["preview", "--help"])
    assert result.exit_code == 0


def test_autostart_subcommand_help(cli_runner):
    """Test autostart subcommand is accessible."""
    result = cli_runner.invoke(app, ["autostart", "--help"])
    assert result.exit_code == 0


def test_status_subcommand_help(cli_runner):
    """Test status subcommand is accessible."""
    result = cli_runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0


def test_invalid_command(cli_runner):
    """Test invalid command returns error."""
    result = cli_runner.invoke(app, ["invalid_command"])
    assert result.exit_code != 0
