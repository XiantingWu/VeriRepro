from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode

_DEFAULT_DATASET_LIMIT = 5 * 1024 * 1024 * 1024
_DEFAULT_MODEL_ARTIFACT_LIMIT = 10 * 1024 * 1024 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_DATASET_SPECS = 32
_MAX_MODEL_ARTIFACT_SPECS = 16
_MAX_METRIC_SPECS = 128
_MAX_ARTIFACT_SPECS = 128


class _StrictManifestLoader(yaml.SafeLoader):
    """Safe YAML loader with deterministic, non-aliasing mapping semantics.

    Repository manifests are untrusted input. SafeLoader prevents arbitrary
    Python object construction, but YAML aliases can still create unexpectedly
    large or recursive object graphs and duplicate keys are ambiguous. Public
    release manifests therefore reject both instead of guessing intent.
    """

    def compose_node(self, parent, index):  # type: ignore[no-untyped-def]
        if self.check_event(AliasEvent):
            raise ValueError("repository manifest YAML aliases are not allowed")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):  # type: ignore[no-untyped-def]
        if not isinstance(node, MappingNode):
            return super().construct_mapping(node, deep=deep)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise ValueError("repository manifest mapping keys must be scalar/hashable") from exc
            if duplicate:
                raise ValueError(f"repository manifest contains duplicate mapping key: {key!r}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    url: str | None = None
    filename: str | None = None
    sha256: str | None = None
    provider: str = "url"
    repo_id: str | None = None
    revision: str = "main"
    path: str | None = None
    record_id: str | None = None
    file: str | None = None
    max_bytes: int = _DEFAULT_DATASET_LIMIT


@dataclass(frozen=True)
class ModelArtifactSpec:
    """A checksum-bound model/checkpoint file materialized read-only for a run."""

    name: str
    sha256: str
    url: str | None = None
    filename: str | None = None
    provider: str = "url"
    repo_id: str | None = None
    revision: str | None = None
    path: str | None = None
    record_id: str | None = None
    file: str | None = None
    max_bytes: int = _DEFAULT_MODEL_ARTIFACT_LIMIT


@dataclass(frozen=True)
class MetricSpec:
    name: str
    paper: float
    tolerance: float = 0.01


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    kind: str
    reference: str
    reproduced: str
    threshold: float = 0.95
    absolute_tolerance: float = 1e-6
    relative_tolerance: float = 0.01


@dataclass(frozen=True)
class ReproManifest:
    command: str | None
    network: bool
    datasets: tuple[DatasetSpec, ...]
    metrics: tuple[MetricSpec, ...]
    gpu: bool = False
    artifacts: tuple[ArtifactSpec, ...] = ()
    model_artifacts: tuple[ModelArtifactSpec, ...] = ()
    scientific_contract_trusted: bool = False
    declared_metric_count: int = 0
    declared_artifact_count: int = 0


def _as_dict(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _bounded_sequence(data: dict[str, Any], key: str, limit: int) -> list[Any]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    if len(value) > limit:
        raise ValueError(f"{key} exceeds host safety limit ({len(value)} > {limit})")
    return value


def _finite_float(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be a finite number")
    return parsed


def _checksum(value: Any, *, label: str, required: bool) -> str | None:
    checksum = str(value).strip().lower() if value else None
    if required and checksum is None:
        raise ValueError(f"{label} requires 'sha256'")
    if checksum is not None and not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError(f"{label} sha256 must be exactly 64 hexadecimal characters")
    return checksum


def _dataset_spec(item: dict[str, Any]) -> DatasetSpec:
    provider = str(item.get("provider") or "url").lower().strip()
    if provider not in {"url", "huggingface", "zenodo"}:
        raise ValueError(f"unsupported dataset provider: {provider}")

    url = str(item["url"]).strip() if item.get("url") else None
    repo_id = str(item["repo_id"]).strip() if item.get("repo_id") else None
    remote_path = str(item["path"]).strip() if item.get("path") else None
    record_id = str(item.get("record_id") or item.get("record") or "").strip() or None
    remote_file = str(item["file"]).strip() if item.get("file") else None

    if provider == "url" and not url:
        raise ValueError("URL dataset requires 'url'")
    if provider == "huggingface" and (not repo_id or not remote_path):
        raise ValueError("Hugging Face dataset requires 'repo_id' and 'path'")
    if provider == "zenodo" and (not record_id or not remote_file):
        raise ValueError("Zenodo dataset requires 'record_id' and 'file'")

    max_bytes = int(item.get("max_bytes", _DEFAULT_DATASET_LIMIT))
    if max_bytes <= 0:
        raise ValueError("dataset max_bytes must be positive")

    return DatasetSpec(
        name=str(item.get("name") or "dataset"),
        url=url,
        filename=str(item["filename"]) if item.get("filename") else None,
        sha256=_checksum(item.get("sha256"), label="dataset", required=False),
        provider=provider,
        repo_id=repo_id,
        revision=str(item.get("revision") or "main"),
        path=remote_path,
        record_id=record_id,
        file=remote_file,
        max_bytes=max_bytes,
    )


def _model_artifact_spec(item: dict[str, Any]) -> ModelArtifactSpec:
    provider = str(item.get("provider") or "url").lower().strip()
    if provider not in {"url", "huggingface", "zenodo"}:
        raise ValueError(f"unsupported model artifact provider: {provider}")

    url = str(item["url"]).strip() if item.get("url") else None
    repo_id = str(item["repo_id"]).strip() if item.get("repo_id") else None
    revision = str(item["revision"]).strip() if item.get("revision") else None
    remote_path = str(item["path"]).strip() if item.get("path") else None
    record_id = str(item.get("record_id") or item.get("record") or "").strip() or None
    remote_file = str(item["file"]).strip() if item.get("file") else None

    if provider == "url" and not url:
        raise ValueError("URL model artifact requires 'url'")
    if provider == "huggingface":
        if not repo_id or not remote_path:
            raise ValueError("Hugging Face model artifact requires 'repo_id' and 'path'")
        if not revision or revision.lower() == "main":
            raise ValueError(
                "Hugging Face model artifact requires an explicit immutable revision, not 'main'"
            )
    if provider == "zenodo" and (not record_id or not remote_file):
        raise ValueError("Zenodo model artifact requires 'record_id' and 'file'")

    max_bytes = int(item.get("max_bytes", _DEFAULT_MODEL_ARTIFACT_LIMIT))
    if max_bytes <= 0:
        raise ValueError("model artifact max_bytes must be positive")
    checksum = _checksum(item.get("sha256"), label="model artifact", required=True)
    assert checksum is not None

    return ModelArtifactSpec(
        name=str(item.get("name") or "model-artifact"),
        sha256=checksum,
        url=url,
        filename=str(item["filename"]) if item.get("filename") else None,
        provider=provider,
        repo_id=repo_id,
        revision=revision,
        path=remote_path,
        record_id=record_id,
        file=remote_file,
        max_bytes=max_bytes,
    )


def _host_trusts_repository_contract() -> bool:
    return os.getenv("VERIREPRO_TRUST_REPOSITORY_CONTRACT", "").strip() == "1"


def load_manifest(
    path: Path | None,
    *,
    trust_scientific_contract: bool | None = None,
) -> ReproManifest:
    """Load execution configuration and only host-authorized scientific expectations.

    The manifest lives inside the third-party research repository. Its command,
    dataset/model-artifact declarations, and network request are configuration
    inputs that are constrained elsewhere. Expected paper metrics and reference
    artifacts are different: automatically trusting them would let a repository
    self-certify PASS. They therefore become active only after explicit host consent.
    """
    trusted = (
        _host_trusts_repository_contract()
        if trust_scientific_contract is None
        else bool(trust_scientific_contract)
    )
    if path is None:
        return ReproManifest(
            command=None,
            network=False,
            datasets=(),
            metrics=(),
            artifacts=(),
            model_artifacts=(),
            scientific_contract_trusted=trusted,
        )
    if path.is_symlink():
        raise ValueError("repository manifest must not be a symbolic link")
    if not path.is_file():
        return ReproManifest(
            command=None,
            network=False,
            datasets=(),
            metrics=(),
            artifacts=(),
            model_artifacts=(),
            scientific_contract_trusted=trusted,
        )
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError("could not inspect repository manifest") from exc
    if size > _MAX_MANIFEST_BYTES:
        raise ValueError(
            f"repository manifest exceeds {_MAX_MANIFEST_BYTES} byte safety limit ({size} bytes)"
        )

    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictManifestLoader) or {}
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError("repository manifest YAML is invalid or exceeds parser safety limits") from exc
    if not isinstance(data, dict):
        raise ValueError("verirepro.yaml must contain a mapping")

    version = int(data.get("version", 1))
    if version != 1:
        raise ValueError(f"unsupported verirepro.yaml version: {version}")

    experiment = _as_dict(data.get("experiment"), "experiment")
    network_value = experiment.get("network", False)
    if not isinstance(network_value, bool):
        raise ValueError("experiment.network must be a boolean")
    gpu_value = experiment.get("gpu", False)
    if not isinstance(gpu_value, bool):
        raise ValueError("experiment.gpu must be a boolean")

    datasets = [
        _dataset_spec(_as_dict(item, "dataset"))
        for item in _bounded_sequence(data, "datasets", _MAX_DATASET_SPECS)
    ]
    model_artifacts = [
        _model_artifact_spec(_as_dict(item, "model artifact"))
        for item in _bounded_sequence(data, "model_artifacts", _MAX_MODEL_ARTIFACT_SPECS)
    ]

    declared_metrics: list[MetricSpec] = []
    for item in _bounded_sequence(data, "metrics", _MAX_METRIC_SPECS):
        item = _as_dict(item, "metric")
        tolerance = _finite_float(item.get("tolerance", 0.01), "metric tolerance")
        if tolerance < 0:
            raise ValueError("metric tolerance must be non-negative")
        declared_metrics.append(
            MetricSpec(
                name=str(item["name"]),
                paper=_finite_float(item["paper"], "metric paper value"),
                tolerance=tolerance,
            )
        )

    declared_artifacts: list[ArtifactSpec] = []
    for item in _bounded_sequence(data, "artifacts", _MAX_ARTIFACT_SPECS):
        item = _as_dict(item, "artifact")
        kind = str(item.get("kind") or "file").lower()
        if kind not in {"figure", "table", "file"}:
            raise ValueError(f"unsupported artifact kind: {kind}")
        threshold = _finite_float(item.get("threshold", 0.95), "artifact threshold")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("artifact threshold must be between 0 and 1")
        absolute_tolerance = _finite_float(
            item.get("absolute_tolerance", 1e-6), "artifact absolute_tolerance"
        )
        relative_tolerance = _finite_float(
            item.get("relative_tolerance", 0.01), "artifact relative_tolerance"
        )
        if absolute_tolerance < 0 or relative_tolerance < 0:
            raise ValueError("artifact tolerances must be non-negative")
        declared_artifacts.append(
            ArtifactSpec(
                name=str(item["name"]),
                kind=kind,
                reference=str(item["reference"]),
                reproduced=str(item["reproduced"]),
                threshold=threshold,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            )
        )

    return ReproManifest(
        command=str(experiment["command"]) if experiment.get("command") else None,
        network=network_value,
        datasets=tuple(datasets),
        gpu=gpu_value,
        metrics=tuple(declared_metrics) if trusted else (),
        artifacts=tuple(declared_artifacts) if trusted else (),
        model_artifacts=tuple(model_artifacts),
        scientific_contract_trusted=trusted,
        declared_metric_count=len(declared_metrics),
        declared_artifact_count=len(declared_artifacts),
    )
