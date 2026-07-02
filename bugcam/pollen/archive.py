"""Archiving interface for Pollen, with a tar-based first implementation.

An Archiver bundles a device's queued items into a single artifact for one upload.
TarArchiver writes an uncompressed tar whose members are named by each item's
canonical v1 key (so the tar is self-describing and the backend can map a member
straight to its destination), shipped to v2/archives/<device>/<ts>.tar. Other
strategies (e.g. compressed, or a different container) can implement the same
interface later.
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
    def key_for(self, device: str, timestamp: str) -> str:
        """The s3_key ``pack`` would upload this device+timestamp bundle to.

        Exposed so the batcher can dedup against already-queued archives before
        packing (packing the same key would overwrite the queued tar's file)."""

    @abstractmethod
    def pack(
        self,
        device: str,
        items: list[UploadRow],
        staging_dir: Path,
        *,
        timestamp: str,
    ) -> Optional[ArchiveArtifact]:
        """Bundle ``items`` into one artifact, or return None if there is nothing.

        Args:
            device: the owning device id; the archive is grouped/keyed under it.
            items: the queued rows to bundle (their staged copies are the bytes).
            staging_dir: directory to write the archive file into locally.
            timestamp: seal time, used in the archive's filename.
        """


class TarArchiver(Archiver):
    def __init__(self, *, archive_key_prefix: str = "v2/archives") -> None:
        self.archive_key_prefix = archive_key_prefix.rstrip("/")

    def key_for(self, device: str, timestamp: str) -> str:
        return f"{self.archive_key_prefix}/{device}/{timestamp}.tar"

    def pack(
        self,
        device: str,
        items: list[UploadRow],
        staging_dir: Path,
        *,
        timestamp: str,
    ) -> Optional[ArchiveArtifact]:
        if not items:
            return None
        staging_dir = Path(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
        s3_key = self.key_for(device, timestamp)
        tar_path = staging_dir / s3_key.replace("/", "_")
        with tarfile.open(tar_path, "w") as tar:  # uncompressed -> valid member offsets
            for item in items:
                tar.add(item.staging_path, arcname=item.s3_key)
        return ArchiveArtifact(path=tar_path, s3_key=s3_key, member_keys=[it.s3_key for it in items])
