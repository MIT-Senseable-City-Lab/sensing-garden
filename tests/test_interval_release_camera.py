"""
interval_release_camera: optionally keep the camera warm between interval chunks.

Default (True) preserves the historical interval-mode behavior: init camera,
record one chunk, release camera, wait. With release_camera_between_chunks=False
on the picamera path, the camera is initialized once and reused across chunks
(no per-chunk teardown or warmup); it is still released when the recording
window closes, on failure recovery, and at shutdown. The OpenCV path always
releases -- stale queued frames would otherwise leak into the next chunk.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import bugcam.edge26.capture.recorder as recorder_module
from bugcam.processing import build_edge26_config

from tests.test_recorder_recovery import (
    install_scripted_camera,
    make_recorder,
    patched_exit,
)


@pytest.fixture(autouse=True)
def fast_waits(monkeypatch):
    monkeypatch.setattr(recorder_module, "RECOVERY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(recorder_module, "NO_CHUNK_RETRY_SECONDS", 0.01)


def make_interval_recorder(tmp_path, **overrides):
    return make_recorder(
        tmp_path, recording_mode="interval", interval_minutes=0, **overrides
    )


def test_default_releases_camera_after_each_chunk(tmp_path, monkeypatch):
    rec = make_interval_recorder(tmp_path)
    cameras = install_scripted_camera(rec, ["ok"])
    patched_exit(monkeypatch)

    rec.start()

    # One camera per chunk: released after the first, rebuilt for the second.
    assert len(cameras) == 2
    assert cameras[0].close.called


def test_keep_warm_reuses_camera_across_chunks(tmp_path, monkeypatch):
    rec = make_interval_recorder(tmp_path, release_camera_between_chunks=False)
    cameras = install_scripted_camera(rec, ["ok", "ok"])
    patched_exit(monkeypatch)

    rec.start()

    # Three chunks, one camera: no per-chunk teardown/re-init.
    assert len(list(tmp_path.glob("*.mp4"))) == 3
    assert len(cameras) == 1
    # Shutdown still releases it.
    assert cameras[0].close.called


def test_keep_warm_failure_still_rebuilds_camera(tmp_path, monkeypatch):
    rec = make_interval_recorder(tmp_path, release_camera_between_chunks=False)
    cameras = install_scripted_camera(rec, ["ok", "fail"])
    exit_mock = patched_exit(monkeypatch)

    rec.start()

    # The failed chunk tore the warm camera down; a fresh one recorded the
    # final chunk.
    assert len(cameras) == 2
    assert cameras[0].stop_recording.called
    assert cameras[0].close.called
    exit_mock.assert_not_called()


class _WindowFake:
    """Open until the first chunk lands, closed until the camera is released,
    open again after that. Fails safe by stopping the recorder if the camera
    is never released, so a broken implementation fails fast instead of
    hanging the test."""

    def __init__(self, rec):
        self.rec = rec
        self.calls = 0

    def is_open(self):
        self.calls += 1
        if self.calls > 20:
            self.rec.stop_event.set()
            return False
        if self.rec.last_chunk_path is None:
            return True
        return self.rec.camera is None

    def describe(self):
        return "scripted window"


def test_keep_warm_releases_camera_while_window_closed(tmp_path, monkeypatch):
    rec = make_interval_recorder(tmp_path, release_camera_between_chunks=False)
    cameras = install_scripted_camera(rec, ["ok"])
    patched_exit(monkeypatch)
    monkeypatch.setattr(recorder_module.time, "sleep", lambda s: None)
    rec.record_window = _WindowFake(rec)

    rec.start()

    # The warm camera was released when the window closed and a fresh one was
    # built when it reopened.
    assert len(cameras) == 2
    assert cameras[0].close.called


def test_opencv_path_always_releases_between_chunks(tmp_path, monkeypatch):
    rec = make_interval_recorder(
        tmp_path, use_picamera=False, release_camera_between_chunks=False
    )
    patched_exit(monkeypatch)
    init_calls = []
    script = iter(["ok"])

    def fake_init():
        init_calls.append(1)
        rec.camera = MagicMock()

    def fake_record_chunk():
        action = next(script, "end")
        path = Path(rec.output_dir) / f"chunk{len(init_calls)}.mp4"
        path.write_bytes(b"data")
        if action == "end":
            rec.stop_event.set()
        return path

    rec._init_camera = fake_init
    rec._start_grabber = lambda: None
    rec._record_chunk = fake_record_chunk

    rec.start()

    # Keep-warm is picamera-only: the OpenCV path re-inits every cycle so
    # stale queued frames can't leak into the next chunk.
    assert len(init_calls) == 2


def _build_config(tmp_path, **overrides):
    return build_edge26_config(
        flick_id="flick01",
        dot_ids=[],
        input_dir=str(tmp_path / "input"),
        output_dir=str(tmp_path / "outputs"),
        model_path=str(tmp_path / "bundle" / "model.hef"),
        labels_path=str(tmp_path / "bundle" / "labels.txt"),
        **overrides,
    )


def test_build_edge26_config_interval_release_camera_default(tmp_path):
    config = _build_config(tmp_path)

    assert config["pipeline"]["interval_release_camera"] is True


def test_build_edge26_config_interval_release_camera_custom(tmp_path):
    config = _build_config(tmp_path, interval_release_camera=False)

    assert config["pipeline"]["interval_release_camera"] is False
