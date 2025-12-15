"""Integration tests for RPi-specific functionality.

These tests verify that system dependencies are properly available.
They will be skipped on non-RPi platforms where dependencies aren't installed.
"""
import sys
import platform
import pytest


def is_raspberry_pi() -> bool:
    """Check if running on Raspberry Pi."""
    return platform.machine() in ["aarch64", "armv7l"] and platform.system() == "Linux"


# Skip all tests in this module if not on RPi
pytestmark = pytest.mark.skipif(
    not is_raspberry_pi(),
    reason="RPi integration tests only run on Raspberry Pi"
)


@pytest.mark.integration
class TestSystemDependencies:
    """Tests that verify system packages are importable on RPi."""

    def test_gi_importable(self):
        """Verify PyGObject (gi) can be imported."""
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst, GLib
        assert Gst is not None
        assert GLib is not None

    def test_hailo_importable(self):
        """Verify Hailo SDK can be imported."""
        import hailo
        assert hailo is not None

    def test_hailo_apps_infra_importable(self):
        """Verify hailo_apps_infra can be imported."""
        import hailo_apps_infra
        from hailo_apps_infra.hailo_rpi_common import (
            get_caps_from_pad,
            get_numpy_from_buffer,
            app_callback_class,
        )
        from hailo_apps_infra.detection_pipeline import GStreamerDetectionApp
        assert hailo_apps_infra is not None
        assert GStreamerDetectionApp is not None

    def test_all_detection_dependencies(self):
        """Verify all dependencies needed by detection.py are available."""
        # These are all the imports detection.py needs
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst, GLib
        import numpy as np
        import cv2
        import hailo
        from hailo_apps_infra.hailo_rpi_common import (
            get_caps_from_pad,
            get_numpy_from_buffer,
            app_callback_class,
        )
        from hailo_apps_infra.detection_pipeline import GStreamerDetectionApp

        # All imports succeeded
        assert True


@pytest.mark.integration
class TestDetectionScript:
    """Tests that verify detection.py can be loaded on RPi."""

    def test_detection_check_dependencies_passes(self):
        """Verify check_dependencies() passes on RPi with all packages installed."""
        from bugcam.pipelines.detection import check_dependencies
        # Should not raise SystemExit
        check_dependencies()

    def test_detection_main_importable(self):
        """Verify detection.py main() can be imported (not run)."""
        from bugcam.pipelines.detection import main
        assert callable(main)
