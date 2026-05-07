"""Shared runtime helpers for BugCam edge26 commands."""
from __future__ import annotations

from pathlib import Path

from bugcam.edge26 import Pipeline, setup_logging
from bugcam.model_bundles import resolve_bundle_reference, resolve_model_path
from bugcam.processing import build_bundle_provenance, build_edge26_config


def resolve_model_assets(model_reference: str) -> tuple[Path, Path]:
    """Resolve the model and labels paths for an edge26 run."""
    bundle = resolve_bundle_reference(model_reference, require_labels=True)
    if bundle is not None:
        return bundle.model_path, bundle.labels_path

    model_path = resolve_model_path(model_reference)
    if model_path is None:
        raise ValueError(f"Model bundle not found: {model_reference}")

    labels_path = model_path.parent / "labels.txt"
    if not labels_path.exists():
        raise ValueError(f"labels.txt not found next to model: {model_path}")

    return model_path, labels_path


def build_pipeline(
    flick_id: str,
    dot_ids: list[str],
    input_dir: Path,
    output_dir: Path,
    model_reference: str,
    recording_mode: str = "continuous",
    recording_interval: int = 5,
    chunk_duration: int = 60,
    fps: int = 30,
    resolution: tuple[int, int] = (1080, 1080),
    enable_recording: bool = True,
    enable_processing: bool = True,
    enable_classification: bool = True,
    continuous_tracking: bool = True,
    detection_config_path: Path | None = None,
) -> Pipeline:
    """Create a configured edge26 pipeline instance."""
    model_path, labels_path = resolve_model_assets(model_reference)
    provenance = build_bundle_provenance(model_path, labels_path)
    config = build_edge26_config(
        flick_id=flick_id,
        dot_ids=dot_ids,
        input_dir=str(input_dir),
        output_dir=str(output_dir),
        model_path=str(model_path),
        labels_path=str(labels_path),
        recording_mode=recording_mode,
        recording_interval_minutes=recording_interval,
        chunk_duration_seconds=chunk_duration,
        fps=fps,
        resolution=resolution,
        enable_recording=enable_recording,
        enable_processing=enable_processing,
        enable_classification=enable_classification,
        continuous_tracking=continuous_tracking,
        model_metadata=provenance,
        detection_config_path=detection_config_path,
    )
    setup_logging(Path(config["paths"]["logs_dir"]))
    return Pipeline(config)


def resolve_bundle_provenance(model_reference: str) -> dict[str, str]:
    """Resolve provenance metadata for the active bundle."""
    model_path, labels_path = resolve_model_assets(model_reference)
    return build_bundle_provenance(model_path, labels_path)


def select_model_reference(model_reference: str | None) -> str:
    """Return the requested model reference or the first installed bundle."""
    if model_reference:
        return model_reference

    bundle = resolve_bundle_reference(None, require_labels=True)
    if bundle is None:
        raise ValueError("No installed model bundles with labels were found. Download one with `bugcam models download <bundle>` or pass --model.")
    return bundle.name
