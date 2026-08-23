from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse

from .config import DatasetSpec, ModelArtifactSpec
from .datasets import DatasetSecurityError, download_datasets

_MODEL_ARTIFACT_PROVENANCE_SCHEMA_VERSION = 1


def _huggingface_model_url(spec: ModelArtifactSpec) -> str:
    assert spec.repo_id and spec.revision and spec.path
    repo_id = quote(spec.repo_id, safe="/")
    revision = quote(spec.revision, safe="")
    remote_path = quote(spec.path, safe="/")
    return f"https://huggingface.co/{repo_id}/resolve/{revision}/{remote_path}?download=true"


def _download_spec(spec: ModelArtifactSpec) -> DatasetSpec:
    """Adapt a strict model artifact to the hardened host file downloader.

    Model/checkpoint files deliberately reuse the dataset downloader's SSRF,
    redirect, byte, checksum, cache, filename, symlink, and atomic-write controls.
    The structured Hugging Face model provider is public-download-only in this
    first resolver slice; no HF credential is forwarded to the experiment.
    """
    provider = spec.provider.lower()
    if provider == "huggingface":
        return DatasetSpec(
            name=spec.name,
            provider="url",
            url=_huggingface_model_url(spec),
            filename=spec.filename,
            sha256=spec.sha256,
            max_bytes=spec.max_bytes,
        )
    if provider == "url":
        return DatasetSpec(
            name=spec.name,
            provider="url",
            url=spec.url,
            filename=spec.filename,
            sha256=spec.sha256,
            max_bytes=spec.max_bytes,
        )
    if provider == "zenodo":
        return DatasetSpec(
            name=spec.name,
            provider="zenodo",
            record_id=spec.record_id,
            file=spec.file,
            filename=spec.filename,
            sha256=spec.sha256,
            max_bytes=spec.max_bytes,
        )
    raise ValueError(f"unsupported model artifact provider: {spec.provider}")


def _source(spec: ModelArtifactSpec) -> dict[str, str]:
    provider = spec.provider.lower()
    if provider == "url":
        parsed = urlparse(spec.url or "")
        return {
            "provider": "url",
            "origin": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
        }
    if provider == "huggingface":
        return {
            "provider": "huggingface",
            "repo_id": spec.repo_id or "",
            "revision": spec.revision or "",
            "path": spec.path or "",
        }
    return {
        "provider": "zenodo",
        "record_id": spec.record_id or "",
        "file": spec.file or "",
    }


def _write_provenance(
    path: Path,
    specs: tuple[ModelArtifactSpec, ...],
    raw_records: list[dict[str, object]],
) -> None:
    if path.is_symlink():
        raise DatasetSecurityError("model artifact provenance destination must not be a symbolic link")
    if len(raw_records) != len(specs):
        raise RuntimeError("model artifact provenance count does not match materialized declarations")

    records: list[dict[str, object]] = []
    for spec, raw in zip(specs, raw_records, strict=True):
        record = dict(raw)
        record["provider"] = spec.provider.lower()
        record["source"] = _source(spec)
        records.append(record)

    payload = {
        "schema_version": _MODEL_ARTIFACT_PROVENANCE_SCHEMA_VERSION,
        "model_artifacts": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def materialize_model_artifacts(
    specs: tuple[ModelArtifactSpec, ...],
    destination: Path,
    *,
    provenance_path: Path | None = None,
) -> list[Path]:
    """Materialize checksum-bound model/checkpoint files on the trusted host.

    Model artifacts never require experiment-container networking: they are
    acquired before Docker starts, verified by SHA-256, and later mounted read-only.
    The existing host download/cache ceilings remain authoritative for this slice.
    """
    if not specs:
        if provenance_path is not None:
            _write_provenance(provenance_path, (), [])
        return []

    adapted = tuple(_download_spec(spec) for spec in specs)
    if provenance_path is None:
        return download_datasets(adapted, destination)

    scratch = provenance_path.with_name(f".{provenance_path.name}.{uuid.uuid4().hex}.datasets")
    try:
        downloaded = download_datasets(adapted, destination, provenance_path=scratch)
        raw = json.loads(scratch.read_text(encoding="utf-8"))
        records = raw.get("datasets") if isinstance(raw, dict) else None
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise RuntimeError("hardened downloader returned malformed model artifact provenance")
        _write_provenance(provenance_path, specs, records)
        return downloaded
    finally:
        scratch.unlink(missing_ok=True)
