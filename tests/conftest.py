import pytest
from pathlib import Path
from typer.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_resources_dir(tmp_path):
    """Create temp resources/ dir with mock model bundles."""
    resources = tmp_path / "resources"
    resources.mkdir()

    for bundle_name, model_bytes in {
        "yolov8m": b"fake model data " * 1000,
        "yolov8s": b"small model " * 500,
    }.items():
        bundle_dir = resources / bundle_name
        bundle_dir.mkdir()
        (bundle_dir / "model.hef").write_bytes(model_bytes)
        (bundle_dir / "labels.txt").write_text("species-a\nspecies-b\n", encoding="utf-8")

    return resources


@pytest.fixture
def make_bundle():
    """Create a model bundle under the provided root path."""

    def _make_bundle(root: Path, name: str, *, labels: bool = True, model_bytes: bytes = b"fake model") -> Path:
        bundle_dir = root / name
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "model.hef").write_bytes(model_bytes)
        if labels:
            (bundle_dir / "labels.txt").write_text("species-a\nspecies-b\n", encoding="utf-8")
        return bundle_dir

    return _make_bundle


@pytest.fixture
def temp_detection_script(tmp_path):
    """Create a mock detection.py script."""
    pipelines = tmp_path / "pipelines"
    pipelines.mkdir()
    script = pipelines / "detection.py"
    script.write_text('''
import sys
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--input")
parser.add_argument("--hef-path")
args = parser.parse_args()

print(f"Mock detection with input={args.input}, model={args.hef_path}")
sys.exit(0)
''')
    return script


@pytest.fixture
def mock_bugcam_structure(tmp_path, temp_resources_dir, temp_detection_script):
    """Create a complete mock bugcam structure."""
    return {
        "root": tmp_path,
        "resources": temp_resources_dir,
        "detection_script": temp_detection_script,
    }
