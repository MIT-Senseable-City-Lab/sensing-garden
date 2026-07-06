"""Pollen: a self-contained, durable device-side upload subsystem.

The app enqueues artifacts (results, heartbeats, logs); Pollen owns the queue,
the upload loop (presign + multipart-resumable transport), batching/archiving,
and cleanup, persisting everything in SQLite so it survives restarts.
"""
from bugcam.pollen.archive import ArchiveArtifact, Archiver, TarArchiver
from bugcam.pollen.pollen import Pollen, PollenConfig
from bugcam.pollen.presign import Presigner, PresignError
from bugcam.pollen.store import PollenStore, UploadRow, UploadStatus
from bugcam.pollen.transport import Uploader

__all__ = [
    "Pollen",
    "PollenConfig",
    "PollenStore",
    "UploadRow",
    "UploadStatus",
    "Presigner",
    "PresignError",
    "Uploader",
    "Archiver",
    "ArchiveArtifact",
    "TarArchiver",
]
