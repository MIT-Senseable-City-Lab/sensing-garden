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


def test_run_subcommand_help(cli_runner):
    """Test run subcommand is accessible."""
    result = cli_runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--resolution" in result.output


def test_run_heartbeat_interval_is_one_minute() -> None:
    """Test run command emits heartbeat snapshots every minute."""
    from bugcam.commands.run import HEARTBEAT_INTERVAL_SECONDS

    assert HEARTBEAT_INTERVAL_SECONDS == 60


def test_process_subcommand_help(cli_runner):
    """Test process subcommand is accessible."""
    result = cli_runner.invoke(app, ["process", "--help"])
    assert result.exit_code == 0


def test_upload_subcommand_help(cli_runner):
    """Test upload subcommand is accessible."""
    result = cli_runner.invoke(app, ["upload", "--help"])
    assert result.exit_code == 0


def test_heartbeat_subcommand_help(cli_runner):
    """Test heartbeat subcommand is accessible."""
    result = cli_runner.invoke(app, ["heartbeat", "--help"])
    assert result.exit_code == 0


def test_environment_subcommand_help(cli_runner):
    """Test environment subcommand is accessible."""
    result = cli_runner.invoke(app, ["environment", "--help"])
    assert result.exit_code == 0


def test_autostart_subcommand_help(cli_runner):
    """Test autostart subcommand is accessible."""
    result = cli_runner.invoke(app, ["autostart", "--help"])
    assert result.exit_code == 0


def test_update_subcommand_help(cli_runner):
    """Test update subcommand is accessible."""
    result = cli_runner.invoke(app, ["update", "--help"])
    assert result.exit_code == 0


def test_status_subcommand_help(cli_runner):
    """Test status subcommand is accessible."""
    result = cli_runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0


def test_invalid_command(cli_runner):
    """Test invalid command returns error."""
    result = cli_runner.invoke(app, ["invalid_command"])
    assert result.exit_code != 0
