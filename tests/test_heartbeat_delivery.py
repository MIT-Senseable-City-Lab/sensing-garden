"""`bugcam run` heartbeat delivery: immediate PUT with durable-spool fallback,
enriched payload sections, and the 5-minute default cadence."""
import json

import pytest

from bugcam.commands import heartbeat as hb
from bugcam.commands import run as run_mod


@pytest.fixture(autouse=True)
def _fake_system_reads(monkeypatch):
    monkeypatch.setattr(hb, "_read_cpu_temperature_celsius", lambda: 42.0)
    monkeypatch.setattr(hb, "_read_uptime_seconds", lambda: 100.0)


class FakePollen:
    def __init__(self, fail_immediate=False):
        self.fail_immediate = fail_immediate
        self.immediate = []      # payloads seen by upload_path_now
        self.spooled = []        # paths seen by enqueue_set

    def upload_path_now(self, path):
        if self.fail_immediate:
            raise RuntimeError("network down")
        self.immediate.append(json.loads(path.read_text()))

    def enqueue_set(self, files, *, device, kind):
        assert kind == "heartbeat"
        self.spooled.extend(files)
        return [1]

    def stats(self):
        return {"pending": 7}


class FakePipeline:
    def health_snapshot(self):
        return {"video_queue": 3}


def _emit(tmp_path, pollen, pipeline=None):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    run_mod._emit_heartbeat(
        "flick01", input_dir, output_dir, ["dot01"], pollen=pollen, pipeline=pipeline
    )
    return list((output_dir / "flick01" / "heartbeats").glob("*.json"))


def test_default_interval_is_five_minutes():
    assert run_mod.HEARTBEAT_INTERVAL_SECONDS == 300


def test_uploads_immediately_and_drops_local_copy(tmp_path):
    pollen = FakePollen()
    leftover = _emit(tmp_path, pollen, pipeline=FakePipeline())

    assert len(pollen.immediate) == 1
    assert pollen.spooled == []
    assert leftover == []  # local copy dropped after successful PUT

    payload = pollen.immediate[0]
    assert payload["pipeline"] == {"video_queue": 3}
    assert payload["upload"] == {"pending": 7}
    assert payload["incoming"]["flick_videos"] == 0


def test_falls_back_to_spool_when_immediate_upload_fails(tmp_path):
    pollen = FakePollen(fail_immediate=True)
    leftover = _emit(tmp_path, pollen)

    assert pollen.immediate == []
    assert len(pollen.spooled) == 1
    assert leftover == []  # producer copy dropped once spooled


def test_without_pollen_keeps_local_snapshot(tmp_path):
    leftover = _emit(tmp_path, pollen=None)
    assert len(leftover) == 1
    payload = json.loads(leftover[0].read_text())
    assert "incoming" in payload
    assert "upload" not in payload
