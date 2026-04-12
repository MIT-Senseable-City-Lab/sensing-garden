"""Tests for runtime storage path resolution."""
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_process_resolves_storage_dirs_at_runtime(tmp_path: Path) -> None:
    from bugcam.commands import process as process_command

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    with patch("bugcam.commands.process.load_device_config") as mock_device_config, \
         patch("bugcam.commands.process.get_input_storage_dir", return_value=input_dir), \
         patch("bugcam.commands.process.get_output_storage_dir", return_value=output_dir), \
         patch("bugcam.commands.process.resolve_bundle_provenance", return_value={"model_id": "bundle", "model_sha256": "abc123456789"}), \
         patch("bugcam.commands.process.build_pipeline") as mock_build_pipeline, \
         patch("bugcam.commands.process.resolve_flick_id", return_value="flick-config"):
        mock_device_config.return_value.dot_ids = ["dot01"]
        mock_build_pipeline.return_value = MagicMock()

        process_command.process(
            input_dir=None,
            output_dir=None,
            model="bundle",
            flick_id=None,
            classification=True,
            continuous_tracking=True,
        )

    assert mock_build_pipeline.call_args.kwargs["input_dir"] == input_dir
    assert mock_build_pipeline.call_args.kwargs["output_dir"] == output_dir


def test_heartbeat_resolves_storage_dirs_at_runtime(tmp_path: Path) -> None:
    from bugcam.commands import heartbeat as heartbeat_command

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"

    with patch("bugcam.commands.heartbeat._resolve_runtime_settings", return_value={"flick_id": "flick", "dot_ids": ["dot01"]}), \
         patch("bugcam.commands.heartbeat.get_input_storage_dir", return_value=input_dir), \
         patch("bugcam.commands.heartbeat.get_output_storage_dir", return_value=output_dir), \
         patch("bugcam.commands.heartbeat.write_heartbeat_snapshot", return_value=output_dir / "heartbeat.json") as mock_write:
        heartbeat_command.heartbeat(flick_id=None, dot_ids=None, input_dir=None, output_dir=None)

    assert mock_write.call_args.kwargs["input_dir"] == input_dir
    assert mock_write.call_args.kwargs["output_dir"] == output_dir


def test_environment_resolves_output_dir_at_runtime(tmp_path: Path) -> None:
    from bugcam.commands import environment as environment_command

    output_dir = tmp_path / "output"

    with patch("bugcam.commands.environment.resolve_flick_id", return_value="flick"), \
         patch("bugcam.commands.environment.get_output_storage_dir", return_value=output_dir), \
         patch("bugcam.commands.environment.collect_environment_reading", return_value=(output_dir / "environment.json", {"ok": True})) as mock_collect:
        environment_command.environment(output_dir=None, device_id=None)

    assert mock_collect.call_args.kwargs["output_dir"] == output_dir


def test_upload_resolves_output_dir_at_runtime(tmp_path: Path) -> None:
    from bugcam.commands import upload as upload_command

    output_dir = tmp_path / "output"

    with patch("bugcam.commands.upload.get_output_storage_dir", return_value=output_dir), \
         patch(
             "bugcam.commands.upload._resolve_runtime_settings",
             return_value={"api_url": "https://api.test", "api_key": "key", "flick_id": "flick", "dot_ids": [], "s3_bucket": "bucket"},
         ), \
         patch("bugcam.commands.upload.watch_uploads") as mock_watch:
        upload_command.upload(
            output_dir=None,
            api_url=None,
            api_key=None,
            bucket=None,
            poll_interval=30,
            delete_after_upload=True,
            flick_id=None,
            dot_ids=None,
        )

    assert mock_watch.call_args.args[0] == output_dir


def test_upload_ready_results_reads_custom_output_dir(tmp_path: Path) -> None:
    from bugcam.commands.upload import upload_ready_results

    output_dir = tmp_path / "custom-output"
    heartbeat_path = output_dir / "flick" / "heartbeats" / "20260412_120000.json"
    heartbeat_path.parent.mkdir(parents=True)
    heartbeat_path.write_text('{"device_id": "flick"}', encoding="utf-8")

    with patch("bugcam.commands.upload.upload_file") as mock_upload_file:
        processed_count, manifest_uploaded = upload_ready_results(
            output_dir=output_dir,
            api_url="https://api.test",
            api_key="key",
            flick_id="flick",
            dot_ids=[],
            delete_after_upload=False,
            manifest_uploaded=False,
        )

    assert processed_count == 1
    assert manifest_uploaded is False
    assert mock_upload_file.call_args.args[2] == heartbeat_path
    assert mock_upload_file.call_args.args[3] == "v1/flick/heartbeats/20260412_120000.json"


def test_run_resolves_storage_dirs_at_runtime(tmp_path: Path) -> None:
    from bugcam.commands import run as run_command

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    pipeline = MagicMock()

    with patch("bugcam.commands.run._acquire_pid_file", return_value=tmp_path / "bugcam.pid"), \
         patch("bugcam.commands.run._release_pid_file"), \
         patch("bugcam.commands.run._check_time_sync", return_value=(True, "ok")), \
         patch("bugcam.commands.run.get_input_storage_dir", return_value=input_dir), \
         patch("bugcam.commands.run.get_output_storage_dir", return_value=output_dir), \
         patch(
             "bugcam.commands.run._resolve_runtime_settings",
             return_value={"api_url": "https://api.test", "api_key": "key", "flick_id": "flick", "dot_ids": [], "s3_bucket": "bucket"},
         ), \
         patch("bugcam.commands.run.select_model_reference", return_value="bundle"), \
         patch("bugcam.commands.run.resolve_bundle_provenance", return_value={"model_id": "bundle"}), \
         patch("bugcam.commands.run.build_pipeline", return_value=pipeline) as mock_build_pipeline, \
         patch("bugcam.commands.run.watch_uploads"), \
         patch("bugcam.commands.run._heartbeat_loop"), \
         patch("bugcam.commands.run._environment_loop"), \
         patch("bugcam.commands.run.upload_ready_results"):
        run_command.run(
            api_url=None,
            api_key=None,
            flick_id=None,
            dot_ids=None,
            input_dir=None,
            output_dir=None,
            model=None,
            mode="continuous",
            interval=5,
            chunk_duration=60,
            resolution="1080x1080",
            bucket=None,
            upload_poll=1,
            delete_after_upload=True,
        )

    assert mock_build_pipeline.call_args.kwargs["input_dir"] == input_dir
    assert mock_build_pipeline.call_args.kwargs["output_dir"] == output_dir
