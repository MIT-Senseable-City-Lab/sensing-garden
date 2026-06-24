"""StagingArea hardlinks sources into a same-mount staging dir."""
import pytest

from bugcam.pollen.staging import STAGING_SUBDIR, CrossMountError, StagingArea


def _write(path, data="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)
    return path


class TestStagedPath:
    def test_mirrors_layout_under_root(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "flick01" / "20260204" / "results.json")
        assert area.staged_path(src) == out / STAGING_SUBDIR / "flick01" / "20260204" / "results.json"

    def test_falls_back_to_basename_off_root(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(tmp_path / "loose.json")  # same mount, not under root
        assert area.staged_path(src) == out / STAGING_SUBDIR / "loose.json"


class TestLink:
    def test_link_creates_hardlink_sharing_inode(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json", "payload")
        dst = area.link(src)
        assert dst.exists()
        assert dst.stat().st_ino == src.stat().st_ino
        assert dst.read_text() == "payload"

    def test_producer_unlink_keeps_staged_data(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json", "payload")
        dst = area.link(src)
        src.unlink()  # producer drops its copy
        assert dst.exists() and dst.read_text() == "payload"

    def test_link_is_idempotent_for_same_inode(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json")
        first = area.link(src)
        second = area.link(src)
        assert first == second

    def test_changed_source_replaces_link(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = out / "a" / "results.json"
        _write(src, "v1")
        area.link(src)
        src.unlink()
        _write(src, "v2")  # new inode, same path
        dst = area.link(src)
        assert dst.read_text() == "v2"
        assert dst.stat().st_ino == src.stat().st_ino

    def test_unlink_removes_staged_copy(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json")
        dst = area.link(src)
        area.unlink(dst)
        assert not dst.exists()


class TestMountValidation:
    def test_source_on_unknown_mount_raises(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        loose = _write(tmp_path / "loose.json")  # same fs, not under root
        area._by_dev.clear()  # simulate a source on a mount with no staging
        with pytest.raises(CrossMountError):
            area._staging_dir(loose.resolve(), loose)
