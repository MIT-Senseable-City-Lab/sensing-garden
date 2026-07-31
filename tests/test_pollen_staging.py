"""StagingArea hardlinks sources into a same-mount staging dir."""
import errno
import os
import shutil

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


def _deny_hardlinks(monkeypatch):
    """Make os.link fail like a filesystem without hardlink support (vfat)."""

    def eperm_link(src, dst, **kwargs):
        raise OSError(errno.EPERM, "Operation not permitted", str(src))

    monkeypatch.setattr(os, "link", eperm_link)


def _part_files(root):
    return [p for p in root.rglob("*.part") if p.is_file()]


class TestCopyFallback:
    """os.link raising EPERM (vfat) falls back to an atomic same-dir copy."""

    def test_eperm_falls_back_to_copy_with_content_and_mtime(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json", "payload")
        os.utime(src, (1_000_000_000, 1_000_000_000))
        _deny_hardlinks(monkeypatch)
        dst = area.link(src)
        assert dst.exists()
        assert dst.read_text() == "payload"
        assert dst.stat().st_ino != src.stat().st_ino  # a copy, not a link
        assert dst.stat().st_mtime == src.stat().st_mtime  # copy2 semantics

    def test_no_part_file_left_after_successful_copy(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json", "payload")
        _deny_hardlinks(monkeypatch)
        area.link(src)
        assert _part_files(out / STAGING_SUBDIR) == []

    def test_reenqueue_of_unchanged_copy_does_not_recopy(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json", "payload")
        _deny_hardlinks(monkeypatch)
        copies = []
        real_copy2 = shutil.copy2

        def counting_copy2(s, d, **kwargs):
            copies.append(str(d))
            return real_copy2(s, d, **kwargs)

        monkeypatch.setattr(shutil, "copy2", counting_copy2)
        first = area.link(src)
        assert len(copies) == 1
        second = area.link(src)
        assert second == first
        assert len(copies) == 1  # unchanged src: no re-copy

    def test_changed_source_replaces_copy_via_temp_rename(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json", "v1")
        _deny_hardlinks(monkeypatch)
        copies = []
        real_copy2 = shutil.copy2

        def counting_copy2(s, d, **kwargs):
            copies.append(str(d))
            return real_copy2(s, d, **kwargs)

        monkeypatch.setattr(shutil, "copy2", counting_copy2)
        dst = area.link(src)
        _write(src, "v2-longer")  # different size
        dst = area.link(src)
        assert dst.read_text() == "v2-longer"
        assert len(copies) == 2
        assert all(d.endswith(".part") for d in copies)  # never copied straight to dst

    def test_same_size_newer_mtime_replaces_copy(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json", "v1")
        os.utime(src, (1_000_000_000, 1_000_000_000))
        _deny_hardlinks(monkeypatch)
        dst = area.link(src)
        src.write_text("v2")  # same size, different content
        os.utime(src, (1_000_000_500, 1_000_000_500))
        dst = area.link(src)
        assert dst.read_text() == "v2"

    def test_stale_part_file_is_consumed_by_next_link(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json", "payload")
        dst = area.staged_path(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        stale = dst.with_name(dst.name + ".part")
        stale.write_text("truncated-junk")  # left by a crash mid-copy
        _deny_hardlinks(monkeypatch)
        result = area.link(src)
        assert result == dst
        assert dst.read_text() == "payload"
        assert _part_files(out / STAGING_SUBDIR) == []

    def test_interrupted_copy_never_exposes_partial_dst(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json", "payload")
        _deny_hardlinks(monkeypatch)
        real_copy2 = shutil.copy2

        def dying_copy2(s, d, **kwargs):
            with open(d, "w") as fh:
                fh.write("par")  # partial write, then the power goes
            raise OSError(errno.EIO, "I/O error")

        monkeypatch.setattr(shutil, "copy2", dying_copy2)
        with pytest.raises(OSError):
            area.link(src)
        assert not area.staged_path(src).exists()  # dst absent, never partial
        monkeypatch.setattr(shutil, "copy2", real_copy2)
        dst = area.link(src)  # retry succeeds and consumes the stale temp
        assert dst.read_text() == "payload"
        assert _part_files(out / STAGING_SUBDIR) == []

    def test_exdev_still_raises_crossmount(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json")

        def exdev_link(s, d, **kwargs):
            raise OSError(errno.EXDEV, "Invalid cross-device link", str(s))

        monkeypatch.setattr(os, "link", exdev_link)
        with pytest.raises(CrossMountError):
            area.link(src)

    def test_other_oserror_still_propagates(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json")

        def eacces_link(s, d, **kwargs):
            raise OSError(errno.EACCES, "Permission denied", str(s))

        monkeypatch.setattr(os, "link", eacces_link)
        with pytest.raises(OSError):
            area.link(src)

    def test_unlink_removes_copied_file(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        area = StagingArea([out])
        src = _write(out / "a" / "results.json", "payload")
        _deny_hardlinks(monkeypatch)
        dst = area.link(src)
        area.unlink(dst)
        assert not dst.exists()
        assert not (out / STAGING_SUBDIR / "a").exists()  # dirs still pruned


class TestPruneEmptyDirs:
    def test_unlink_prunes_emptied_dirs_up_to_staging_root(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        dst = area.link(_write(out / "FLIK4" / "20260627_200000_000000" / "crops" / "x.jpg"))
        area.unlink(dst)
        staging = out / STAGING_SUBDIR
        assert not (staging / "FLIK4").exists()  # mirrored tree gone
        assert staging.exists()  # staging root itself preserved

    def test_unlink_keeps_dirs_with_siblings(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        keep = area.link(_write(out / "FLIK4" / "a.json"))
        drop = area.link(_write(out / "FLIK4" / "deep" / "b.json"))
        area.unlink(drop)
        assert not drop.parent.exists()  # emptied subdir pruned
        assert keep.exists()  # sibling and its dir untouched

    def test_retain_prunes_emptied_staging_dirs(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        dst = area.link(_write(out / "FLIK4" / "20260627" / "results.json"))
        area.retain(dst)
        assert not (out / STAGING_SUBDIR / "FLIK4").exists()


class TestMountValidation:
    def test_source_on_unknown_mount_raises(self, tmp_path):
        out = tmp_path / "out"
        area = StagingArea([out])
        loose = _write(tmp_path / "loose.json")  # same fs, not under root
        area._by_dev.clear()  # simulate a source on a mount with no staging
        with pytest.raises(CrossMountError):
            area._staging_dir(loose.resolve(), loose)
