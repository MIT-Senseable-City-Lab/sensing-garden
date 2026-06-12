"""Shared runtime helpers for BugCam edge26 commands."""
from __future__ import annotations

from pathlib import Path
from typing import Any

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
    app_config: dict[str, Any],
    *,
    flick_id: str,
    dot_ids: list[str],
    input_dir: Path,
    output_dir: Path,
    model_reference: str,
) -> Pipeline:
    """Create a configured edge26 pipeline from the resolved central config.

    All capture/pipeline/detection/tracking values are read from
    ``app_config`` (see :mod:`bugcam.app_config`). Callers overlay any
    explicit overrides onto ``app_config`` before calling.
    """
    model_path, labels_path = resolve_model_assets(model_reference)
    provenance = build_bundle_provenance(model_path, labels_path)
    config = build_edge26_config(
        app_config,
        flick_id=flick_id,
        dot_ids=dot_ids,
        input_dir=str(input_dir),
        output_dir=str(output_dir),
        model_path=str(model_path),
        labels_path=str(labels_path),
        model_metadata=provenance,
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
