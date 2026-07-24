"""Tests for the main bugcam CLI structure."""
import pytest
import typer
from bugcam.cli import app
from tests.helpers import strip_ansi


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


@pytest.mark.xfail(reason="SG-029: --help assertion brittle to Typer/Rich rendering", strict=False)
def test_run_subcommand_help(cli_runner):
    """Test run subcommand is accessible."""
    result = cli_runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--resolution" in strip_ansi(result.output)


def test_run_heartbeat_interval_is_five_minutes() -> None:
    """Test run command emits heartbeat snapshots every five minutes by default."""
    from bugcam.commands.run import HEARTBEAT_INTERVAL_SECONDS

    assert HEARTBEAT_INTERVAL_SECONDS == 300


def test_resolve_heartbeat_interval_cli_wins(monkeypatch) -> None:
    """An explicit --heartbeat-interval overrides config and default."""
    from bugcam.commands import run

    monkeypatch.setattr(run, "load_config", lambda: {"heartbeat_interval": 99})
    assert run._resolve_heartbeat_interval(5) == 5.0


def test_resolve_heartbeat_interval_from_config(monkeypatch) -> None:
    """With no CLI flag, the config key is used."""
    from bugcam.commands import run

    monkeypatch.setattr(run, "load_config", lambda: {"heartbeat_interval": 15})
    assert run._resolve_heartbeat_interval(None) == 15.0


def test_resolve_heartbeat_interval_default(monkeypatch) -> None:
    """With neither CLI flag nor config, falls back to 300s."""
    from bugcam.commands import run

    monkeypatch.setattr(run, "load_config", lambda: {})
    assert run._resolve_heartbeat_interval(None) == 300.0


def test_heartbeat_loop_waits_configured_interval(monkeypatch) -> None:
    """The heartbeat loop sleeps for the configured interval, not the default 60s."""
    from bugcam.commands import run

    monkeypatch.setattr(run, "write_heartbeat_snapshot", lambda *a, **k: __import__("pathlib").Path("hb.json"))

    waited: list[float] = []

    class _StopAfterOne:
        def __init__(self) -> None:
            self._calls = 0

        def is_set(self) -> bool:
            self._calls += 1
            return self._calls > 1  # run the body exactly once

        def wait(self, timeout: float) -> None:
            waited.append(timeout)

    run._heartbeat_loop("FLIK4", None, None, [], _StopAfterOne(), None, 5)
    assert waited == [5]


def test_run_video_sample_interval_default_is_ten() -> None:
    """Test the FLIK sample-video default is 1 saved per 10 processed videos."""
    from bugcam.commands.run import DEFAULT_VIDEO_SAMPLE_INTERVAL

    assert DEFAULT_VIDEO_SAMPLE_INTERVAL == 10


def test_resolve_video_sample_interval_cli_wins(monkeypatch) -> None:
    """An explicit --video-sample-interval overrides config and default."""
    from bugcam.commands import run

    monkeypatch.setattr(run, "load_config", lambda: {"video_sample_interval": 99})
    assert run._resolve_video_sample_interval(5) == 5


def test_resolve_video_sample_interval_from_config(monkeypatch) -> None:
    """With no CLI flag, the config key is used."""
    from bugcam.commands import run

    monkeypatch.setattr(run, "load_config", lambda: {"video_sample_interval": 15})
    assert run._resolve_video_sample_interval(None) == 15


def test_resolve_video_sample_interval_default(monkeypatch) -> None:
    """With neither CLI flag nor config, falls back to 10."""
    from bugcam.commands import run

    monkeypatch.setattr(run, "load_config", lambda: {})
    assert run._resolve_video_sample_interval(None) == 10


def test_resolve_video_sample_interval_zero_disables_sampling(monkeypatch) -> None:
    """0 is a valid value (disables sample-video saving), not rejected."""
    from bugcam.commands import run

    monkeypatch.setattr(run, "load_config", lambda: {})
    assert run._resolve_video_sample_interval(0) == 0


def test_resolve_video_sample_interval_rejects_negative_cli(monkeypatch) -> None:
    """A negative --video-sample-interval is invalid and rejected at resolve time."""
    from bugcam.commands import run

    monkeypatch.setattr(run, "load_config", lambda: {})
    with pytest.raises(typer.BadParameter):
        run._resolve_video_sample_interval(-1)


def test_resolve_video_sample_interval_rejects_negative_config(monkeypatch) -> None:
    """A negative config-file value is invalid and rejected at resolve time."""
    from bugcam.commands import run

    monkeypatch.setattr(run, "load_config", lambda: {"video_sample_interval": -3})
    with pytest.raises(typer.BadParameter):
        run._resolve_video_sample_interval(None)


def test_process_subcommand_help(cli_runner):
    """Test process subcommand is accessible."""
    result = cli_runner.invoke(app, ["process", "--help"])
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
