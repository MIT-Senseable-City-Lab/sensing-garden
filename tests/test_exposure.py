"""Unit tests for the AE shutter-cap tuning helpers (no hardware required)."""

import sys
from types import SimpleNamespace

import pytest

from bugcam.edge26.capture.exposure import (
    DEFAULT_MAX_GAIN,
    DEFAULT_MIN_SHUTTER_US,
    build_capped_tuning,
    capped_exposure_mode,
)

STOCK_TUNING = {
    "version": 1,
    "rpi.agc": {
        "channels": [
            {"exposure_modes": {"normal": {"shutter": [100, 66666], "gain": [1.0, 16.0]}}},
            {"exposure_modes": {"normal": {"shutter": [100, 66666], "gain": [1.0, 16.0]}}},
        ]
    },
}


def make_fake_picamera2(model="imx708", tuning=STOCK_TUNING, cameras=(("imx708", 0),)):
    """Build a fake picamera2 module with the Picamera2 static methods the
    helper relies on, and install it into sys.modules."""
    class FakePicamera2:
        @staticmethod
        def global_camera_info():
            return [{"Model": m} for m, _ in cameras]

        @staticmethod
        def load_tuning_file(name, dir=None):
            if name != f"{cameras[0][0]}.json":
                raise RuntimeError(f"unexpected tuning file {name}")
            return tuning

        @staticmethod
        def find_tuning_algo(tuning, name):
            return tuning[name]

    mod = SimpleNamespace(Picamera2=FakePicamera2)
    sys.modules["picamera2"] = mod
    return mod


@pytest.fixture
def fake_picamera2(monkeypatch):
    monkeypatch.setattr(sys, "modules", dict(sys.modules))


class TestCappedExposureMode:
    def test_default_cap_ends_on_1000(self):
        mode = capped_exposure_mode(1000)
        assert mode["shutter"][-1] == 1000
        assert mode["gain"][-1] == DEFAULT_MAX_GAIN

    def test_equal_length_lists(self):
        mode = capped_exposure_mode(1000)
        assert len(mode["shutter"]) == len(mode["gain"])

    def test_monotonic_non_decreasing(self):
        mode = capped_exposure_mode(1000)
        assert all(a <= b for a, b in zip(mode["shutter"], mode["shutter"][1:]))
        assert all(a <= b for a, b in zip(mode["gain"], mode["gain"][1:]))

    def test_shutter_ramps_then_caps(self):
        mode = capped_exposure_mode(1000)
        # First entries ramp toward the cap at minimum gain...
        assert mode["shutter"][0] == DEFAULT_MIN_SHUTTER_US
        assert mode["gain"][0] == 1.0
        # ...and once the cap is reached, every later shutter stays at it.
        cap_idx = next(i for i, s in enumerate(mode["shutter"]) if s == 1000)
        assert all(s == 1000 for s in mode["shutter"][cap_idx:])

    def test_custom_cap(self):
        mode = capped_exposure_mode(2000)
        assert mode["shutter"][-1] == 2000
        assert max(mode["shutter"]) == 2000

    def test_zero_cap_rejected(self):
        with pytest.raises(ValueError):
            capped_exposure_mode(0)

    def test_cap_below_min_shutter_rejected(self):
        with pytest.raises(ValueError):
            capped_exposure_mode(DEFAULT_MIN_SHUTTER_US - 1)


class TestBuildCappedTuning:
    def test_patches_normal_mode_in_all_channels(self, fake_picamera2):
        make_fake_picamera2()
        tuning = build_capped_tuning(1000)
        assert tuning is not None
        agc = tuning["rpi.agc"]
        for channel in agc["channels"]:
            normal = channel["exposure_modes"]["normal"]
            assert normal["shutter"][-1] == 1000

    def test_zero_cap_disables(self, fake_picamera2):
        make_fake_picamera2()
        assert build_capped_tuning(0) is None

    def test_no_cameras_returns_none(self, fake_picamera2):
        make_fake_picamera2(cameras=())
        assert build_capped_tuning(1000) is None

    def test_missing_agc_channels_returns_none(self, fake_picamera2):
        make_fake_picamera2(tuning={"version": 1, "rpi.agc": {}})
        assert build_capped_tuning(1000) is None

    def test_errors_degrade_to_none(self, fake_picamera2):
        make_fake_picamera2(tuning="not a dict")

        class Boom:
            @staticmethod
            def global_camera_info():
                raise RuntimeError("no camera")

        sys.modules["picamera2"].Picamera2 = Boom
        assert build_capped_tuning(1000) is None
