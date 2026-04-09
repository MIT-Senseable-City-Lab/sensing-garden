"""Tests for BugCam edge26 processing integration."""
import hashlib
from pathlib import Path
from unittest.mock import patch

from bugcam.processing import build_bundle_provenance, build_edge26_config


def test_build_edge26_config_resolves_paths(tmp_path: Path, monkeypatch) -> None:
    config = build_edge26_config(
        flick_id="flick01",
        dot_ids=["dot01", "dot02"],
        input_dir=str(tmp_path / "input"),
        output_dir=str(tmp_path / "outputs"),
        model_path=str(tmp_path / "bundle" / "model.hef"),
        labels_path=str(tmp_path / "bundle" / "labels.txt"),
        recording_mode="interval",
        recording_interval=7,
        chunk_duration=90,
        fps=24,
        resolution=(1920, 1080),
        enable_recording=True,
        enable_processing=True,
        enable_classification=False,
        continuous_tracking=False,
    )
    assert config["device"]["flick_id"] == "flick01"
    assert config["device"]["dot_ids"] == ["dot01", "dot02"]
    assert config["paths"]["input_storage"].endswith("input")
    assert config["paths"]["logs_dir"].endswith("outputs/flick01/logs")
    assert config["output"]["results_dir"].endswith("outputs")
    assert config["pipeline"]["recording_mode"] == "interval"
    assert config["pipeline"]["recording_interval_minutes"] == 7
    assert config["capture"]["chunk_duration_seconds"] == 90
    assert config["capture"]["fps"] == 24
    assert config["capture"]["resolution"] == [1920, 1080]
    assert config["pipeline"]["enable_classification"] is False
    assert config["pipeline"]["continuous_tracking"] is False


def test_build_bundle_provenance_hashes_active_bundle(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle-a"
    bundle_dir.mkdir()
    model_path = bundle_dir / "model.hef"
    labels_path = bundle_dir / "labels.txt"
    model_path.write_bytes(b"hef-data")
    labels_path.write_text("species-a\n", encoding="utf-8")

    provenance = build_bundle_provenance(model_path, labels_path)

    assert provenance["model_id"] == "bundle-a"
    assert provenance["model_sha256"] == hashlib.sha256(b"hef-data").hexdigest()
    assert provenance["labels_sha256"] == hashlib.sha256(b"species-a\n").hexdigest()


def test_process_uses_device_config_flick_id(tmp_path: Path) -> None:
    from bugcam.commands import process as process_command

    with patch('bugcam.commands.process.load_device_config') as mock_device_config, \
         patch('bugcam.commands.process.resolve_bundle_provenance', return_value={"model_id": "bundle", "model_sha256": "abc123456789"}), \
         patch('bugcam.commands.process.build_pipeline') as mock_build_pipeline, \
         patch('bugcam.commands.process.resolve_flick_id', return_value="flick-config"):
        mock_device_config.return_value.flick_id = "flick-config"
        mock_device_config.return_value.dot_ids = ["dot01"]

        process_command.process(
            input_dir=tmp_path / "input",
            output_dir=tmp_path / "output",
            model="bundle",
            flick_id=None,
            classification=True,
            continuous_tracking=True,
        )

    assert mock_build_pipeline.call_args.kwargs["flick_id"] == "flick-config"
    assert mock_build_pipeline.call_args.kwargs["dot_ids"] == ["dot01"]


def test_run_resolves_flick_id_from_config() -> None:
    from bugcam.commands.run import _resolve_runtime_settings

    with patch('bugcam.commands.run.load_config', return_value={"api_key": "key", "s3_bucket": "bucket"}), \
         patch('bugcam.commands.run.resolve_flick_id', return_value="flick-config"):
        settings = _resolve_runtime_settings(None, None, None, None, None)

    assert settings["flick_id"] == "flick-config"
