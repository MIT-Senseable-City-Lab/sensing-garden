"""PollenConfig is built from CLI args / config files (resolved in the run cmd),
and the resolved knobs reach the Uploader.
"""
from bugcam.commands import run
from bugcam.pollen.integration import build_pollen_config
from bugcam.pollen.transport import DEFAULT_MULTIPART_THRESHOLD, DEFAULT_PART_SIZE


class TestResolveSettings:
    def test_batch_cli_wins(self, mocker):
        mocker.patch.object(run, "load_config", return_value={"pollen_batch": False})
        s = run._resolve_pollen_settings(True, upload_poll=30)
        assert s["batch"] is True

    def test_config_used_when_cli_unset(self, mocker):
        mocker.patch.object(run, "load_config", return_value={
            "pollen_batch": True,
            "pollen_poll_interval": 5, "pollen_multipart_threshold": 111, "pollen_part_size": 222,
        })
        s = run._resolve_pollen_settings(None, upload_poll=30)
        assert s == {"batch": True, "poll_interval": 5.0,
                     "multipart_threshold": 111, "part_size": 222}

    def test_defaults(self, mocker):
        mocker.patch.object(run, "load_config", return_value={})
        s = run._resolve_pollen_settings(None, upload_poll=30)
        assert s["batch"] is False
        assert s["poll_interval"] == 30.0  # falls back to --upload-poll
        assert s["multipart_threshold"] == DEFAULT_MULTIPART_THRESHOLD
        assert s["part_size"] == DEFAULT_PART_SIZE


class TestBuildConfig:
    def test_knobs_land_in_config(self, tmp_path):
        cfg = build_pollen_config(
            tmp_path / "out", state_dir=tmp_path / "state",
            poll_interval=7, multipart_threshold=999, part_size=512, batch=True,
        )
        assert cfg.poll_interval == 7.0
        assert cfg.multipart_threshold == 999
        assert cfg.part_size == 512
        assert cfg.batch is True
        assert cfg.db_path == tmp_path / "state" / "pollen" / "pollen.db"

    def test_part_size_reaches_uploader(self, tmp_path):
        from bugcam.pollen.pollen import Pollen
        cfg = build_pollen_config(tmp_path / "out", state_dir=tmp_path / "state", part_size=4096,
                                  multipart_threshold=8192)
        pol = Pollen(cfg, presigner=None)
        assert pol.uploader.part_size == 4096
        assert pol.uploader.multipart_threshold == 8192


