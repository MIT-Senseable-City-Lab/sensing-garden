"""Tests for BugCam edge26 processing integration."""
import hashlib
from pathlib import Path

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
