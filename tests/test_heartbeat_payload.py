"""Heartbeat payload: incoming-directory backlog plus optional pipeline/upload
sections supplied by `bugcam run`."""
import pytest

from bugcam.commands import heartbeat as hb


@pytest.fixture(autouse=True)
def _fake_system_reads(monkeypatch):
    monkeypatch.setattr(hb, "_read_cpu_temperature_celsius", lambda: 42.0)
    monkeypatch.setattr(hb, "_read_uptime_seconds", lambda: 100.0)
    monkeypatch.setattr(hb, "_read_network_usage", lambda: [])


def _payload(input_dir, **kwargs):
    return hb.build_heartbeat_payload("flick01", input_dir, ["dot01"], **kwargs)


class TestIncoming:
    def test_counts_flick_videos_and_bytes(self, tmp_path):
        (tmp_path / "flick01_20260714_120000.mp4").write_bytes(b"abc")
        (tmp_path / "flick01_20260714_121000.mp4").write_bytes(b"abcde")
        (tmp_path / "other_20260714_120000.mp4").write_bytes(b"x")  # wrong device
        (tmp_path / "flick01_notes.txt").write_text("x")  # not a video

        incoming = _payload(tmp_path)["incoming"]

        assert incoming["flick_videos"] == 2
        assert incoming["flick_video_bytes"] == 8
        assert incoming["dot_dirs"] == 0
        assert incoming["ready_dot_tracks"] == 0

    def test_counts_dot_dirs_and_ready_tracks(self, tmp_path):
        ready = tmp_path / "dot01_20260714" / "crops" / "track-a_120000"
        ready.mkdir(parents=True)
        (ready / "done.txt").write_text("")
        not_ready = tmp_path / "dot01_20260714" / "crops" / "track-b_120100"
        not_ready.mkdir()
        (tmp_path / "dot99_20260714").mkdir()  # unconfigured device ignored

        incoming = _payload(tmp_path)["incoming"]

        assert incoming["dot_dirs"] == 1
        assert incoming["ready_dot_tracks"] == 1

    def test_empty_input_dir_reports_zeros(self, tmp_path):
        incoming = _payload(tmp_path)["incoming"]
        assert incoming == {
            "flick_videos": 0,
            "flick_video_bytes": 0,
            "dot_dirs": 0,
            "ready_dot_tracks": 0,
        }


class TestNetworkUsageReader:
    """_read_network_usage parses /proc/net/dev-style content into per-interface
    rx/tx byte counters, excluding loopback."""

    @pytest.fixture(autouse=True)
    def _fake_system_reads(self, monkeypatch):
        # Override the module-level autouse fixture, which stubs out
        # _read_network_usage itself -- these tests exercise the real thing.
        monkeypatch.setattr(hb, "_read_cpu_temperature_celsius", lambda: 42.0)
        monkeypatch.setattr(hb, "_read_uptime_seconds", lambda: 100.0)

    PROC_NET_DEV = (
        "Inter-|   Receive                                                |  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
        "    lo:    1234      10    0    0    0     0          0         0     1234      10    0    0    0     0       0          0\n"
        "  eth0:  567890      20    0    0    0     0          0         0   123456      30    0    0    0     0       0          0\n"
        " wlan0:   11111       5    0    0    0     0          0         0    22222       8    0    0    0     0       0          0\n"
    )

    def test_excludes_loopback_and_reports_rx_tx_bytes(self, monkeypatch, tmp_path):
        proc_net_dev = tmp_path / "net_dev"
        proc_net_dev.write_text(self.PROC_NET_DEV, encoding="utf-8")
        monkeypatch.setattr(hb, "_PROC_NET_DEV_PATH", proc_net_dev)

        interfaces = hb._read_network_usage()

        assert interfaces == [
            {"interface": "eth0", "rx_bytes": 567890, "tx_bytes": 123456},
            {"interface": "wlan0", "rx_bytes": 11111, "tx_bytes": 22222},
        ]

    def test_missing_proc_file_returns_empty_list(self, monkeypatch, tmp_path):
        monkeypatch.setattr(hb, "_PROC_NET_DEV_PATH", tmp_path / "missing")

        assert hb._read_network_usage() == []

    def test_malformed_line_is_skipped_not_fatal(self, monkeypatch, tmp_path):
        proc_net_dev = tmp_path / "net_dev"
        proc_net_dev.write_text(
            "Inter-|   Receive\n face |bytes\n  bad_line_no_colon\n  eth0:  100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(hb, "_PROC_NET_DEV_PATH", proc_net_dev)

        assert hb._read_network_usage() == [{"interface": "eth0", "rx_bytes": 100, "tx_bytes": 200}]


class TestNetworkUsageInPayload:
    def test_network_interfaces_included_in_payload(self, monkeypatch, tmp_path):
        fake_interfaces = [{"interface": "wlan0", "rx_bytes": 111, "tx_bytes": 222}]
        monkeypatch.setattr(hb, "_read_network_usage", lambda: fake_interfaces)

        payload = _payload(tmp_path)

        assert payload["network_interfaces"] == fake_interfaces


class TestOptionalSections:
    def test_absent_by_default(self, tmp_path):
        payload = _payload(tmp_path)
        assert "pipeline" not in payload
        assert "upload" not in payload

    def test_included_when_supplied(self, tmp_path):
        payload = _payload(
            tmp_path,
            pipeline_status={"video_queue": 3},
            upload_status={"pending": 7},
        )
        assert payload["pipeline"] == {"video_queue": 3}
        assert payload["upload"] == {"pending": 7}
