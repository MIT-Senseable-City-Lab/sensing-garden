"""Wiring helpers that build a Pollen instance from bugcam runtime settings.

Keeps construction details (state-dir paths, presigner, archiver selection) out
of the app entrypoint so producers just call ``pollen.enqueue_set(...)``. The config
object (PollenConfig) is built here from settings resolved in the run command.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from bugcam.pollen.archive import TarArchiver
from bugcam.pollen.pollen import Pollen, PollenConfig
from bugcam.pollen.presign import Presigner
from bugcam.pollen.staging import STAGING_SUBDIR
from bugcam.pollen.transport import DEFAULT_MULTIPART_THRESHOLD, DEFAULT_PART_SIZE


def build_pollen_config(output_dir: Path, *, state_dir: Path, **overrides) -> PollenConfig:
    """Build the PollenConfig from resolved knobs (CLI args / config file). ``state_dir``
    is resolved on the bugcam side and passed in -- the pollen package owns no config
    resolution of its own."""
    base = Path(state_dir) / "pollen"
    # Staging co-locates with output_dir so hardlink-on-enqueue stays on one mount
    # (os.link -> EXDEV across mounts); the db can live elsewhere under state_dir.
    # TODO: multi-mount sources (e.g. DOT data on a separate disk) need a staging
    # dir per source mount; StagingArea handles that, wire it once DOT lands.
    return PollenConfig(
        db_path=base / "pollen.db",
        output_root=Path(output_dir),
        staging_dir=Path(output_dir) / STAGING_SUBDIR,
        poll_interval=float(overrides.get("poll_interval", 10.0)),
        multipart_threshold=int(overrides.get("multipart_threshold", DEFAULT_MULTIPART_THRESHOLD)),
        part_size=int(overrides.get("part_size", DEFAULT_PART_SIZE)),
        batch=bool(overrides.get("batch", False)),
        delete_after_upload=bool(overrides.get("delete_after_upload", True)),
        retain_uploaded=bool(overrides.get("retain_uploaded", False)),
        reconcile_grace_seconds=float(overrides.get("reconcile_grace_seconds", 300.0)),
    )


def build_pollen(
    output_dir: Path,
    api_url: str,
    api_key: str,
    *,
    config: PollenConfig | None = None,
    state_dir: Path | None = None,
    enqueue_source: Optional[Callable[[Pollen], None]] = None,
    **overrides,
) -> Pollen:
    """Construct a Pollen owning uploads out of ``output_dir``."""
    config = config or build_pollen_config(output_dir, state_dir=state_dir, **overrides)
    presigner = Presigner(api_url, api_key)
    archiver = TarArchiver() if config.batch else None
    return Pollen(config, presigner=presigner, archiver=archiver, enqueue_source=enqueue_source)
