"""Tests for bugcam detect command."""
import subprocess
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from bugcam.cli import app
from bugcam.commands.detect import _resolve_model_path, get_python_for_detection


class TestResolveModelPath:
    """Tests for _resolve_model_path helper function."""

    def test_resolve_none_no_models_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test auto-detect returns None when no bundles exist."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        with patch("bugcam.model_bundles.LOCAL_BUNDLES_DIR", tmp_path / "resources"):
            result = _resolve_model_path(None)
        assert result is None

    def test_resolve_none_finds_cache_model(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test auto-detect finds the first installed bundle in cache."""
        cache_dir = tmp_path / "cache" / "bugcam" / "models" / "cached_model"
        cache_dir.mkdir(parents=True)
        model_file = cache_dir / "model.hef"
        model_file.write_bytes(b"fake model")
        (cache_dir / "labels.txt").write_text("species-a\n", encoding="utf-8")

        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

        result = _resolve_model_path(None)
        assert result == model_file

    def test_resolve_direct_path_exists(self, temp_resources_dir: Path) -> None:
        """Test direct path to existing .hef file."""
        model_path = temp_resources_dir / "yolov8m" / "model.hef"
        model_path.write_bytes(b"fake model content")

        result = _resolve_model_path(str(model_path))
        assert result == model_path

    def test_resolve_direct_path_not_exists(self) -> None:
        """Test direct path to non-existent file returns None."""
        result = _resolve_model_path("/nonexistent/path/model.hef")
        assert result is None

    def test_resolve_direct_path_wrong_extension(self, tmp_path: Path) -> None:
        """Test direct path with non-.hef extension returns None."""
        wrong_file = tmp_path / "model.txt"
        wrong_file.write_text("not a hef file")

        result = _resolve_model_path(str(wrong_file))
        assert result is None

    def test_resolve_name_not_found_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test bundle name returns None when not found."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        with patch("bugcam.model_bundles.LOCAL_BUNDLES_DIR", tmp_path / "resources"):
            result = _resolve_model_path("nonexistent_model")
        assert result is None

    def test_resolve_name_finds_in_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test bundle name resolution finds model.hef in cache."""
        cache_dir = tmp_path / "cache" / "bugcam" / "models" / "yolov8m"
        cache_dir.mkdir(parents=True)
        model_file = cache_dir / "model.hef"
        model_file.write_bytes(b"fake model")
        (cache_dir / "labels.txt").write_text("species-a\n", encoding="utf-8")

        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        result = _resolve_model_path("yolov8m")
        assert result == model_file


class TestDetectStart:
    """Tests for detect start command."""

    def test_detect_start_help(self, cli_runner: CliRunner) -> None:
        """Test detect start help text."""
        result = cli_runner.invoke(app, ["detect", "start", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output
        assert "--output" in result.output
        assert "--quiet" in result.output
        assert "--duration" in result.output

    @patch('bugcam.commands.detect._resolve_model_path')
    def test_detect_start_no_model_error(self, mock_resolve: MagicMock, cli_runner: CliRunner) -> None:
        """Test detect start fails gracefully when no model found."""
        mock_resolve.return_value = None

        result = cli_runner.invoke(app, ["detect", "start"])
        assert result.exit_code == 1
        assert "error" in result.output.lower() or "no model" in result.output.lower()

    @patch('bugcam.commands.detect.preflight_check', return_value=True)
    @patch('bugcam.commands.detect.subprocess.Popen')
    @patch('bugcam.commands.detect._resolve_model_path')
    def test_detect_start_calls_subprocess(
        self,
        mock_resolve: MagicMock,
        mock_popen: MagicMock,
        mock_preflight: MagicMock,
        cli_runner: CliRunner,
    ) -> None:
        """Test detect start calls subprocess with correct args."""
        mock_resolve.return_value = Path("/fake/model.hef")

        # Mock the detection script existence
        with patch.object(Path, 'exists', return_value=True):
            mock_process = MagicMock()
            mock_process.stdout = iter([])
            mock_process.wait.return_value = 0
            mock_popen.return_value = mock_process

            result = cli_runner.invoke(app, ["detect", "start", "--quiet"])

            # Verify subprocess was called with correct args
            assert mock_popen.called
            call_args = mock_popen.call_args[0][0]
            assert "--input" in call_args
            assert "rpi" in call_args
            assert "--hef-path" in call_args

    @patch('bugcam.commands.detect._resolve_model_path')
    def test_detect_start_duration_zero_fails(self, mock_resolve: MagicMock, cli_runner: CliRunner) -> None:
        """Test detect start with duration=0 fails with exit code 1."""
        mock_resolve.return_value = Path("/fake/model.hef")

        result = cli_runner.invoke(app, ["detect", "start", "--duration", "0"])
        assert result.exit_code == 1
        assert "duration must be positive" in result.output.lower()

    @patch('bugcam.commands.detect._resolve_model_path')
    def test_detect_start_duration_negative_fails(self, mock_resolve: MagicMock, cli_runner: CliRunner) -> None:
        """Test detect start with negative duration fails with exit code 1."""
        mock_resolve.return_value = Path("/fake/model.hef")

        result = cli_runner.invoke(app, ["detect", "start", "--duration", "-5"])
        assert result.exit_code == 1
        assert "duration must be positive" in result.output.lower()


class TestPythonInterpreterSelection:
    """Tests for Python interpreter selection (RPi5 vs Mac)."""

    @patch('bugcam.config.platform.system', return_value='Linux')
    def test_get_python_returns_system_python_on_linux(self, mock_system: MagicMock, tmp_path: Path) -> None:
        """On Linux (RPi5) without hailo venv, should return /usr/bin/python3."""
        # No hailo venv exists, so should fall back to system Python
        with patch.object(Path, 'home', return_value=tmp_path):
            result = get_python_for_detection()
            assert result == "/usr/bin/python3"

    @patch('bugcam.config.platform.system', return_value='Linux')
    def test_get_python_uses_hailo_venv_when_available(self, mock_system: MagicMock, tmp_path: Path) -> None:
        """On Linux with hailo venv, should use hailo venv Python."""
        # Create fake hailo venv
        hailo_python = tmp_path / ".local" / "share" / "bugcam" / "hailo-venv" / "bin" / "python"
        hailo_python.parent.mkdir(parents=True)
        hailo_python.touch()

        with patch.object(Path, 'home', return_value=tmp_path):
            result = get_python_for_detection()
            assert result == str(hailo_python)

    @patch('bugcam.config.platform.system', return_value='Darwin')
    def test_get_python_returns_sys_executable_on_mac(self, mock_system: MagicMock) -> None:
        """On Mac (Darwin), should return sys.executable."""
        result = get_python_for_detection()
        assert result == sys.executable

    @patch('bugcam.commands.detect.preflight_check', return_value=True)
    @patch('bugcam.config.platform.system', return_value='Linux')
    @patch('bugcam.commands.detect.subprocess.Popen')
    @patch('bugcam.commands.detect._resolve_model_path')
    def test_detect_uses_system_python_on_rpi(
        self, mock_resolve: MagicMock, mock_popen: MagicMock,
        mock_system: MagicMock, mock_preflight: MagicMock, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """On RPi5 (Linux) without hailo venv, detect should use /usr/bin/python3."""
        mock_resolve.return_value = Path("/fake/model.hef")

        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        with patch.object(Path, 'home', return_value=tmp_path):
            result = cli_runner.invoke(app, ["detect", "start", "--quiet"])

        # Verify subprocess was called with system Python
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert call_args[0] == "/usr/bin/python3", f"Expected /usr/bin/python3 but got {call_args[0]}"


class TestPreflightCheck:
    """Tests for preflight dependency check."""

    @patch('bugcam.utils.platform.system', return_value='Darwin')
    def test_preflight_returns_true_on_non_linux(self, mock_system: MagicMock) -> None:
        """Preflight check should return True on non-Linux (can't check)."""
        from bugcam.utils import preflight_check
        assert preflight_check() is True

    @patch('bugcam.utils.platform.system', return_value='Linux')
    @patch('bugcam.utils.get_python_for_detection', return_value='/usr/bin/python3')
    @patch('bugcam.utils.subprocess.run')
    def test_preflight_checks_hailo_apps_import(
        self, mock_run: MagicMock, mock_get_python: MagicMock, mock_system: MagicMock
    ) -> None:
        """Preflight check should verify hailo_apps import (not hailo_apps_infra)."""
        from bugcam.utils import preflight_check

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = preflight_check()
        assert result is True

        # Verify it checks "hailo_apps"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args == ['/usr/bin/python3', '-c', 'import gi, hailo, hailo_apps, numpy, cv2']

    @patch('bugcam.utils.platform.system', return_value='Linux')
    @patch('bugcam.utils.get_python_for_detection', return_value='/usr/bin/python3')
    @patch('bugcam.utils.subprocess.run')
    def test_preflight_returns_false_on_import_failure(
        self, mock_run: MagicMock, mock_get_python: MagicMock, mock_system: MagicMock
    ) -> None:
        """Preflight check should return False when imports fail."""
        from bugcam.utils import preflight_check

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_run.return_value = mock_result

        result = preflight_check()
        assert result is False

    @patch('bugcam.utils.platform.system', return_value='Linux')
    @patch('bugcam.utils.get_python_for_detection', return_value='/usr/bin/python3')
    @patch('bugcam.utils.subprocess.run', side_effect=Exception("Test error"))
    def test_preflight_returns_false_on_exception(
        self, mock_run: MagicMock, mock_get_python: MagicMock, mock_system: MagicMock
    ) -> None:
        """Preflight check should return False on exception."""
        from bugcam.utils import preflight_check

        result = preflight_check()
        assert result is False

    @patch('bugcam.commands.detect.preflight_check', return_value=False)
    @patch('bugcam.commands.detect._resolve_model_path')
    def test_detect_fails_when_preflight_fails(
        self, mock_resolve: MagicMock, mock_preflight: MagicMock, cli_runner: CliRunner
    ) -> None:
        """Detect should exit with error when preflight check fails."""
        mock_resolve.return_value = Path("/fake/model.hef")

        with patch.object(Path, 'exists', return_value=True):
            result = cli_runner.invoke(app, ["detect", "start"])
            assert result.exit_code == 1
            assert "missing" in result.output.lower() or "dependencies" in result.output.lower()
            assert "bugcam doctor" in result.output.lower()


class TestDetectionPipelineImports:
    """Tests that detection.py can import detection_handler when run as standalone script.

    This catches regressions where detection.py fails to import modules when spawned
    as a subprocess (since it runs with system Python, not the bugcam venv).
    """

    def test_detection_handler_importable_from_pipeline_context(self) -> None:
        """Verify detection_handler can be imported using the path-based import in detection.py."""
        # Simulate how detection.py imports detection_handler
        detection_script = Path(__file__).parent.parent / "bugcam" / "pipelines" / "detection.py"
        package_dir = detection_script.parent.parent

        # This is the same logic used in detection.py
        original_path = sys.path.copy()
        try:
            if str(package_dir) not in sys.path:
                sys.path.insert(0, str(package_dir))
            from detection_handler import process_detections, format_detection_output
            assert callable(process_detections)
            assert callable(format_detection_output)
        finally:
            sys.path = original_path

    def test_detection_script_imports_work_as_subprocess(self) -> None:
        """Run detection.py import logic as subprocess to verify it works standalone.

        This test actually spawns a subprocess (like the real detect command does)
        to verify the import path manipulation works correctly.
        """
        detection_script = Path(__file__).parent.parent / "bugcam" / "pipelines" / "detection.py"

        # Create a test script that mimics the import logic in detection.py
        test_code = f'''
import sys
from pathlib import Path

# Same import logic as detection.py
_package_dir = Path("{detection_script}").resolve().parent.parent
if str(_package_dir) not in sys.path:
    sys.path.insert(0, str(_package_dir))

try:
    from detection_handler import process_detections, format_detection_output
    print("IMPORT_SUCCESS")
except ImportError as e:
    print(f"IMPORT_FAILED: {{e}}")
    sys.exit(1)
'''
        result = subprocess.run(
            [sys.executable, "-c", test_code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert "IMPORT_SUCCESS" in result.stdout, f"Unexpected output: {result.stdout}"
