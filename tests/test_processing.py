"""Tests for BugCam edge26 processing integration."""
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from bugcam.processing import ProcessorManager, build_bundle_provenance, build_edge26_config


def test_build_edge26_config_resolves_paths(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    bundle_dir = cache_dir / "bugcam" / "models" / "test-bundle"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "model.hef").write_bytes(b"hef")
    (bundle_dir / "labels.txt").write_text("species-a\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    monkeypatch.setenv("BUGCAM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BUGCAM_EDGE26_MODEL", "test-bundle")

    config = build_edge26_config(output_root=tmp_path / "outputs")
    assert config["classification"]["model"].endswith("test-bundle/model.hef")
    assert config["classification"]["labels"].endswith("labels.txt")
    assert config["output"]["results_dir"].endswith("outputs")


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


def test_processor_manager_reuses_processor_for_same_continuity_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BUGCAM_EDGE26_CONTINUOUS_TRACKING", "1")
    adapter = MagicMock()
    adapter.process.return_value = {"processor": "edge26"}

    with patch("bugcam.processing.Edge26ProcessorAdapter", return_value=adapter):
        manager = ProcessorManager()
        job = {"job_id": "1", "source_type": "rpi", "logical_device_id": "rpi-1", "continuity_key": "rpi-1"}
        manager.process(tmp_path / "a.mp4", tmp_path / "out1", job)
        manager.process(tmp_path / "b.mp4", tmp_path / "out2", job)

    adapter.process.assert_called()
    adapter.reset.assert_not_called()
    assert adapter.clear.call_count == 2


def test_processor_manager_resets_when_continuity_key_changes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BUGCAM_EDGE26_CONTINUOUS_TRACKING", "1")
    adapter = MagicMock()
    adapter.process.return_value = {"processor": "edge26"}

    with patch("bugcam.processing.Edge26ProcessorAdapter", return_value=adapter):
        manager = ProcessorManager()
        job_a = {"job_id": "1", "source_type": "rpi", "logical_device_id": "rpi-1", "continuity_key": "rpi-1"}
        job_b = {"job_id": "2", "source_type": "iphone", "logical_device_id": "iphone-1", "continuity_key": "iphone-1"}
        manager.process(tmp_path / "a.mp4", tmp_path / "out1", job_a)
        manager.process(tmp_path / "b.mp4", tmp_path / "out2", job_b)

    adapter.reset.assert_called_once()


def test_processor_manager_resets_when_continuous_tracking_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BUGCAM_EDGE26_CONTINUOUS_TRACKING", "0")
    adapter = MagicMock()
    adapter.process.return_value = {"processor": "edge26"}

    with patch("bugcam.processing.Edge26ProcessorAdapter", return_value=adapter):
        manager = ProcessorManager()
        job = {"job_id": "1", "source_type": "rpi", "logical_device_id": "rpi-1", "continuity_key": "rpi-1"}
        manager.process(tmp_path / "a.mp4", tmp_path / "out1", job)
        manager.process(tmp_path / "b.mp4", tmp_path / "out2", job)

    adapter.reset.assert_called_once()
