import pytest
from pathlib import Path
from typer.testing import CliRunner
from bugcam.cli import app


@pytest.fixture
def cli_runner():
    """Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_resources_dir(tmp_path):
    """Create temp resources/ dir with mock .hef files."""
    resources = tmp_path / "resources"
    resources.mkdir()

    # Create fake .hef files
    (resources / "yolov8m.hef").write_bytes(b"fake model data " * 1000)  # ~16KB
    (resources / "yolov8s.hef").write_bytes(b"small model " * 500)  # ~6KB

    return resources


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
