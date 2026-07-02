"""Archiving interface for Pollen, with a tar-based first implementation.

An Archiver bundles a group of queued items into a single artifact for one
upload. TarArchiver writes an uncompressed tar whose members are named by each
item's canonical v1 key (so the tar is self-describing and the backend can map a
member straight to its destination), shipped to v2/archives/<group>/<group>_<ts>.tar.
Other strategies (e.g. compressed, or a different container) can implement the
same interface later.
"""
from __future__ import annotations

import tarfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from bugcam.pollen.store import UploadRow


@dataclass(frozen=True)
class ArchiveArtifact:
    path: Path              # the staged archive file to upload
    s3_key: str             # where the archive is uploaded
    member_keys: list[str]  # the s3_keys bundled, to mark uploaded once shipped


class Archiver(ABC):
    @abstractmethod
    def pack(
        self,
        group: str,
        items: list[UploadRow],
        staging_dir: Path,
        *,
        timestamp: str,
    ) -> Optional[ArchiveArtifact]:
        """Bundle ``items`` into one artifact, or return None if there is nothing."""


class TarArchiver(Archiver):
    def __init__(self, *, archive_key_prefix: str = "v2/archives") -> None:
        self.archive_key_prefix = archive_key_prefix.rstrip("/")

    def pack(
        self,
        group: str,
        items: list[UploadRow],
        staging_dir: Path,
        *,
        timestamp: str,
    ) -> Optional[ArchiveArtifact]:
        if not items:
            return None
        staging_dir = Path(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
        s3_key = f"{self.archive_key_prefix}/{group}/{group}_{timestamp}.tar"
        tar_path = staging_dir / s3_key.replace("/", "_")
        with tarfile.open(tar_path, "w") as tar:  # uncompressed -> valid member offsets
            for item in items:
                tar.add(item.staging_path, arcname=item.s3_key)
        return ArchiveArtifact(path=tar_path, s3_key=s3_key, member_keys=[it.s3_key for it in items])
