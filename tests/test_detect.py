"""Tests for bugcam detect command."""
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
        """Test auto-detect returns None when no .hef files exist."""
        # Mock both cache and resources directories to be empty
        cache_dir = tmp_path / "cache"
        resources_dir = tmp_path / "resources"
        cache_dir.mkdir()
        resources_dir.mkdir()

        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        with patch('bugcam.commands.detect.Path') as mock_path:
            mock_path.home.return_value = tmp_path
            mock_path.return_value.__truediv__ = Path.__truediv__
            # Make the resources_dir path resolve to our empty tmp dir
            original_file = Path(__file__).parent.parent / "bugcam" / "commands" / "detect.py"
            mock_path.__file__ = str(original_file)

            # Actually just test the real function with no models available
            with patch('pathlib.Path.glob', return_value=[]):
                result = _resolve_model_path(None)
                assert result is None

    def test_resolve_none_finds_cache_model(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test auto-detect finds first .hef in cache directory."""
        cache_dir = tmp_path / ".cache" / "bugcam" / "models"
        cache_dir.mkdir(parents=True)
        model_file = cache_dir / "cached_model.hef"
        model_file.write_bytes(b"fake model")

        monkeypatch.setattr(Path, 'home', lambda: tmp_path)

        result = _resolve_model_path(None)
        assert result == model_file

    def test_resolve_direct_path_exists(self, temp_resources_dir: Path) -> None:
        """Test direct path to existing .hef file."""
        model_path = temp_resources_dir / "test_model.hef"
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
        """Test model name returns None when not found in cache or resources."""
        # Create empty cache and resources directories
        cache_dir = tmp_path / ".cache" / "bugcam" / "models"
        cache_dir.mkdir(parents=True)

        monkeypatch.setattr(Path, 'home', lambda: tmp_path)

        result = _resolve_model_path("nonexistent_model")
        assert result is None

    def test_resolve_name_finds_in_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test model name resolution finds model in cache directory."""
        cache_dir = tmp_path / ".cache" / "bugcam" / "models"
        cache_dir.mkdir(parents=True)
        model_file = cache_dir / "yolov8m.hef"
        model_file.write_bytes(b"fake model")

        monkeypatch.setattr(Path, 'home', lambda: tmp_path)

        result = _resolve_model_path("yolov8m")
        assert result == model_file

    def test_resolve_name_adds_hef_extension(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test model name without .hef extension gets it added."""
        cache_dir = tmp_path / ".cache" / "bugcam" / "models"
        cache_dir.mkdir(parents=True)
        model_file = cache_dir / "model.hef"
        model_file.write_bytes(b"fake model")

        monkeypatch.setattr(Path, 'home', lambda: tmp_path)

        result = _resolve_model_path("model")  # No .hef extension
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

    @patch('bugcam.commands.detect.subprocess.Popen')
    @patch('bugcam.commands.detect._resolve_model_path')
    def test_detect_start_calls_subprocess(
        self, mock_resolve: MagicMock, mock_popen: MagicMock, cli_runner: CliRunner
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

    @patch('bugcam.utils.platform.system', return_value='Linux')
    def test_get_python_returns_system_python_on_linux(self, mock_system: MagicMock, tmp_path: Path) -> None:
        """On Linux (RPi5) without hailo venv, should return /usr/bin/python3."""
        # No hailo venv exists, so should fall back to system Python
        with patch.object(Path, 'home', return_value=tmp_path):
            result = get_python_for_detection()
            assert result == "/usr/bin/python3"

    @patch('bugcam.utils.platform.system', return_value='Linux')
    def test_get_python_uses_hailo_venv_when_available(self, mock_system: MagicMock, tmp_path: Path) -> None:
        """On Linux with hailo venv, should use hailo venv Python."""
        # Create fake hailo venv
        hailo_python = tmp_path / "hailo-rpi5-examples" / "venv_hailo_rpi_examples" / "bin" / "python"
        hailo_python.parent.mkdir(parents=True)
        hailo_python.touch()

        with patch.object(Path, 'home', return_value=tmp_path):
            result = get_python_for_detection()
            assert result == str(hailo_python)

    @patch('bugcam.utils.platform.system', return_value='Darwin')
    def test_get_python_returns_sys_executable_on_mac(self, mock_system: MagicMock) -> None:
        """On Mac (Darwin), should return sys.executable."""
        result = get_python_for_detection()
        assert result == sys.executable

    @patch('bugcam.utils.preflight_check', return_value=True)
    @patch('bugcam.utils.platform.system', return_value='Linux')
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
    @patch('bugcam.commands.detect.get_python_for_detection', return_value='/usr/bin/python3')
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
    @patch('bugcam.commands.detect.get_python_for_detection', return_value='/usr/bin/python3')
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
    @patch('bugcam.commands.detect.get_python_for_detection', return_value='/usr/bin/python3')
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
