"""Per-mount hardlink staging for Pollen.

Hardlinks can't cross filesystems, so the staged copy must live on the same mount
as the source file. StagingArea co-locates a staging dir with each source root and
hardlinks enqueued files into it, mirroring their layout. Pollen uploads from (and
later unlinks) the staged copy, leaving the producer's file untouched.

NOTE: multiple source roots (the per-mount logic below) is for a future multi-mount
setup (e.g. DOT data on a separate disk). Today only a single root is wired and
tested; the multi-root paths are unexercised. See spooler-refactor spec open #3.
"""
from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

STAGING_SUBDIR = ".pollen-staging"
RETAINED_SUBDIR = ".pollen-retained"


class CrossMountError(Exception):
    """A source file lives on a mount with no co-located staging area."""


class StagingArea:
    def __init__(self, source_roots, *, subdir: str = STAGING_SUBDIR, retained_subdir: str = RETAINED_SUBDIR) -> None:
        self.subdir = subdir
        self.retained_subdir = retained_subdir
        self._roots: list[tuple[Path, Path]] = []  # (resolved root, staging dir)
        self._by_dev: dict[int, Path] = {}
        for root in source_roots:
            root = Path(root)
            root.mkdir(parents=True, exist_ok=True)
            staging = root / subdir
            staging.mkdir(parents=True, exist_ok=True)
            if staging.stat().st_dev != root.stat().st_dev:
                raise CrossMountError(f"staging {staging} is not on the same mount as {root}")
            self._roots.append((root.resolve(), staging))
            self._by_dev.setdefault(staging.stat().st_dev, staging)

    def _staging_dir(self, resolved: Path, src: Path) -> Path:
        for root, staging in self._roots:
            if resolved == root or root in resolved.parents:
                return staging
        staging = self._by_dev.get(src.stat().st_dev)
        if staging is None:
            raise CrossMountError(f"no staging on the mount holding {src}")
        return staging

    def staged_path(self, src: Path) -> Path:
        """Where ``src`` would be staged, mirroring its layout under its root."""
        resolved = Path(src).resolve()
        staging = self._staging_dir(resolved, Path(src))
        root = staging.parent  # staging == root / subdir
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            rel = Path(resolved.name)
        return staging / rel

    def link(self, src: Path) -> Path:
        """Hardlink ``src`` into staging and return the staged path. Idempotent:
        re-linking the same inode is a no-op; a changed source replaces the link."""
        src = Path(src)
        dst = self.staged_path(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if dst.stat().st_ino == src.stat().st_ino:
                return dst
            dst.unlink()
        try:
            os.link(src, dst)
        except FileExistsError:
            pass  # raced another enqueue; the link is what we wanted
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise CrossMountError(f"{src} and {dst} are on different mounts") from exc
            if exc.errno == errno.EPERM:
                shutil.copy2(src, dst)
            else:
                raise
        return dst

    def unlink(self, staged_path: Path) -> None:
        staged_path = Path(staged_path)
        staged_path.unlink(missing_ok=True)
        self._prune_empty_dirs(staged_path.parent)

    def _prune_empty_dirs(self, start: Path) -> None:
        """Remove now-empty dirs from ``start`` upward, stopping at (and never
        removing) the staging root that contains it. A no-op if ``start`` is not
        under a known staging dir, so the mirrored tree never lingers empty."""
        start = Path(start)
        staging = next((s for _root, s in self._roots if s == start or s in start.parents), None)
        if staging is None:
            return
        current = start
        while current != staging:
            try:
                current.rmdir()
            except OSError:
                return  # non-empty or already gone -> stop climbing
            current = current.parent

    def retain(self, staged_path: Path) -> Path:
        """Move a staged copy into the retained area (same mount), out of staging.
        Returns the retained path; a no-op-safe fallback to unlink if it is gone."""
        staged_path = Path(staged_path)
        for root, staging in self._roots:
            try:
                rel = staged_path.relative_to(staging)
            except ValueError:
                continue
            dst = root / self.retained_subdir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if staged_path.exists():
                os.replace(staged_path, dst)  # same mount -> atomic rename
            self._prune_empty_dirs(staged_path.parent)
            return dst
        self.unlink(staged_path)  # not under a known staging dir; nothing to retain
        return staged_path

    def iter_links(self):
        """Yield every staged file across all staging dirs (for reconcile)."""
        for _root, staging in self._roots:
            if staging.exists():
                for path in staging.rglob("*"):
                    if path.is_file():
                        yield path
