"""Vendored hierarchical classifier from edge26 with BugCam-safe error handling."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class HierarchicalClassification:
    """Classification result with family, genus, and species predictions."""

    family: str
    genus: str
    species: str
    family_confidence: float
    genus_confidence: float
    species_confidence: float
    family_probs: List[float] = field(default_factory=list)
    genus_probs: List[float] = field(default_factory=list)
    species_probs: List[float] = field(default_factory=list)


def _lookup_species(species_name: str) -> Tuple[str, str]:
    import requests

    url = f"https://api.gbif.org/v1/species/match?name={species_name}&verbose=true"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    status = data.get("status")
    if status not in ("ACCEPTED", "SYNONYM"):
        raise RuntimeError(f"{species_name}: not found in GBIF (status={status})")

    family = data.get("family")
    genus = data.get("genus")
    if not family or not genus:
        raise RuntimeError(f"{species_name}: GBIF response missing family/genus")
    return family, genus


def get_taxonomy(species_list: List[str], cache_path: Optional[Path] = None) -> dict:
    """Build taxonomy from GBIF with optional local caching."""
    species_for_gbif = [s for s in species_list if s.lower() != "unknown"]
    cache_key = hashlib.sha256("\n".join(species_list).encode("utf-8")).hexdigest()

    if cache_path and cache_path.exists():
        try:
            cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = cache_data.get(cache_key)
            if cached:
                return cached
        except Exception:
            logger.warning("Ignoring unreadable taxonomy cache: %s", cache_path)

    taxonomy: dict = {1: [], 2: {}, 3: {}}
    for species_name in species_for_gbif:
        family, genus = _lookup_species(species_name)
        taxonomy[3][species_name] = genus
        taxonomy[2][genus] = family
        if family not in taxonomy[1]:
            taxonomy[1].append(family)

    if len(species_for_gbif) != len(species_list):
        taxonomy[1].append("Unknown")
        taxonomy[2]["Unknown"] = "Unknown"
        taxonomy[3]["unknown"] = "Unknown"

    taxonomy[1] = sorted(set(taxonomy[1]))

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {}
        if cache_path.exists():
            try:
                cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                cache_data = {}
        cache_data[cache_key] = taxonomy
        cache_path.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")

    return taxonomy


class HailoClassifier:
    """Hailo-based hierarchical classifier with lazy runtime imports."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.model_path = Path(config["model"])
        self._input_size: Optional[list[int]] = config.get("input_size")
        self.cache_path: Optional[Path] = Path(config["taxonomy_cache"]) if config.get("taxonomy_cache") else None

        self._hef = None
        self._vdevice = None
        self._network_group = None
        self._network_group_params = None
        self._input_vstream_params = None
        self._output_vstream_params = None
        self._hailo = None

        self.family_list: List[str] = []
        self.genus_list: List[str] = []
        self.species_list: List[str] = []
        self.species_to_genus: Dict[str, str] = {}
        self.genus_to_family: Dict[str, str] = {}

    def _load_model(self) -> None:
        if self._hef is not None:
            return
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")

        try:
            from hailo_platform import (
                ConfigureParams,
                FormatType,
                HailoSchedulingAlgorithm,
                HailoStreamInterface,
                HEF,
                InferVStreams,
                InputVStreamParams,
                OutputVStreamParams,
                VDevice,
            )
        except ImportError as exc:
            raise RuntimeError("hailo_platform is required for edge26 classification") from exc

        self._hailo = {
            "ConfigureParams": ConfigureParams,
            "FormatType": FormatType,
            "HailoSchedulingAlgorithm": HailoSchedulingAlgorithm,
            "HailoStreamInterface": HailoStreamInterface,
            "HEF": HEF,
            "InferVStreams": InferVStreams,
            "InputVStreamParams": InputVStreamParams,
            "OutputVStreamParams": OutputVStreamParams,
            "VDevice": VDevice,
        }

        self._hef = HEF(str(self.model_path))
        params = VDevice.create_params()
        params.scheduling_algorithm = HailoSchedulingAlgorithm.NONE
        self._vdevice = VDevice(params=params)
        configure_params = ConfigureParams.create_from_hef(
            hef=self._hef,
            interface=HailoStreamInterface.PCIe,
        )
        network_groups = self._vdevice.configure(self._hef, configure_params)
        self._network_group = network_groups[0]
        self._network_group_params = self._network_group.create_params()
        self._input_vstream_params = InputVStreamParams.make(
            self._network_group,
            quantized=False,
            format_type=FormatType.FLOAT32,
        )
        self._output_vstream_params = OutputVStreamParams.make(
            self._network_group,
            quantized=False,
            format_type=FormatType.FLOAT32,
        )
        self._load_labels()

    def _load_labels(self) -> None:
        labels_path = self.config.get("labels")
        if not labels_path:
            self._load_labels_fallback()
            return

        labels_path = Path(labels_path)
        if not labels_path.exists():
            self._load_labels_fallback()
            return

        self.species_list = [line.strip() for line in labels_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        taxonomy = get_taxonomy(self.species_list, cache_path=self.cache_path)
        self.family_list = taxonomy[1]
        self.genus_list = sorted(taxonomy[2].keys())
        self.species_to_genus = taxonomy[3]
        self.genus_to_family = taxonomy[2]

    def _load_labels_fallback(self) -> None:
        output_infos = self._hef.get_output_vstream_infos()
        for index, info in enumerate(output_infos):
            count = info.shape[-1]
            if index == 0:
                self.family_list = [f"family_{i}" for i in range(count)]
            elif index == 1:
                self.genus_list = [f"genus_{i}" for i in range(count)]
            else:
                self.species_list = [f"class_{i}" for i in range(count)]

        if len(output_infos) == 1:
            count = output_infos[0].shape[-1]
            self.species_list = [f"class_{i}" for i in range(count)]
            self.family_list = list(self.species_list)
            self.genus_list = list(self.species_list)

    def classify(self, crop: np.ndarray) -> HierarchicalClassification:
        self._load_model()
        preprocessed = self._preprocess(crop)
        raw_outputs = self._run_inference(preprocessed)
        family_probs, genus_probs, species_probs = self._parse_outputs(raw_outputs)

        family_idx = int(np.argmax(family_probs))
        genus_idx = int(np.argmax(genus_probs))
        species_idx = int(np.argmax(species_probs))

        return HierarchicalClassification(
            family=self._safe_label(self.family_list, family_idx, "Family"),
            genus=self._safe_label(self.genus_list, genus_idx, "Genus"),
            species=self._safe_label(self.species_list, species_idx, "Species"),
            family_confidence=float(family_probs[family_idx]),
            genus_confidence=float(genus_probs[genus_idx]),
            species_confidence=float(species_probs[species_idx]),
            family_probs=family_probs.tolist(),
            genus_probs=genus_probs.tolist(),
            species_probs=species_probs.tolist(),
        )

    def hierarchical_aggregate(self, classifications: List[HierarchicalClassification]) -> Optional[Dict]:
        if not classifications:
            return None

        family_scores: dict[str, float] = {}
        for item in classifications:
            family_scores[item.family] = family_scores.get(item.family, 0.0) + item.family_confidence
        best_family = max(family_scores.items(), key=lambda pair: pair[1])[0]

        genus_scores: dict[str, float] = {}
        for item in classifications:
            if self.genus_to_family.get(item.genus, best_family) == best_family:
                genus_scores[item.genus] = genus_scores.get(item.genus, 0.0) + item.genus_confidence
        best_genus = max(genus_scores.items(), key=lambda pair: pair[1])[0] if genus_scores else classifications[0].genus

        species_scores: dict[str, float] = {}
        for item in classifications:
            if self.species_to_genus.get(item.species, best_genus) == best_genus:
                species_scores[item.species] = species_scores.get(item.species, 0.0) + item.species_confidence
        best_species = max(species_scores.items(), key=lambda pair: pair[1])[0] if species_scores else classifications[0].species

        return {
            "family": best_family,
            "genus": best_genus,
            "species": best_species,
            "family_confidence": family_scores.get(best_family, 0.0) / len(classifications),
            "genus_confidence": genus_scores.get(best_genus, 0.0) / max(len(classifications), 1),
            "species_confidence": species_scores.get(best_species, 0.0) / max(len(classifications), 1),
        }

    def _preprocess(self, crop: np.ndarray) -> np.ndarray:
        height, width = self._input_size or self._infer_input_size()
        resized = cv2.resize(crop, (width, height))
        preprocessed = resized.astype(np.float32)
        if self.config.get("normalize", False):
            preprocessed /= 255.0
            preprocessed[:, :, 0] = (preprocessed[:, :, 0] - 0.485) / 0.229
            preprocessed[:, :, 1] = (preprocessed[:, :, 1] - 0.456) / 0.224
            preprocessed[:, :, 2] = (preprocessed[:, :, 2] - 0.406) / 0.225
        return np.expand_dims(preprocessed, axis=0)

    def _infer_input_size(self) -> list[int]:
        input_info = self._hef.get_input_vstream_infos()[0]
        height, width = input_info.shape[:2]
        return [height, width]

    def _run_inference(self, input_tensor: np.ndarray) -> dict:
        InferVStreams = self._hailo["InferVStreams"]
        input_name = self._hef.get_input_vstream_infos()[0].name
        with InferVStreams(
            self._network_group,
            self._input_vstream_params,
            self._output_vstream_params,
        ) as infer_pipeline:
            with self._network_group.activate(self._network_group_params):
                return infer_pipeline.infer({input_name: input_tensor})

    def _parse_outputs(self, raw_outputs: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        outputs = list(raw_outputs.values())
        if len(outputs) == 1:
            species_probs = self._softmax(np.squeeze(outputs[0]))
            return species_probs, species_probs, species_probs
        family_probs = self._softmax(np.squeeze(outputs[0]))
        genus_probs = self._softmax(np.squeeze(outputs[1]))
        species_probs = self._softmax(np.squeeze(outputs[2]))
        return family_probs, genus_probs, species_probs

    def _safe_label(self, labels: List[str], index: int, prefix: str) -> str:
        if 0 <= index < len(labels):
            return labels[index]
        return f"{prefix}_{index}"

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        logits = logits - np.max(logits)
        exp = np.exp(logits)
        return exp / np.sum(exp)
