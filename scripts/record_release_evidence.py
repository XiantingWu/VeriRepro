from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_CORPUS = Path("benchmarks/real-paper-smoke.json")
_PINNED_ARXIV_SOURCE = re.compile(r"^\d{4}\.\d{4,5}v\d+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_DECIMAL_ID = re.compile(r"^[1-9][0-9]*$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$", re.IGNORECASE)


class EvidencePromotionError(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise EvidencePromotionError(f"non-finite JSON number is not allowed: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidencePromotionError(f"could not read evidence JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvidencePromotionError(f"evidence JSON must contain an object: {path}")
    return payload


def _project_version(root: Path) -> str:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def _corpus_digest(root: Path) -> str:
    return hashlib.sha256((root / _CORPUS).read_bytes()).hexdigest()


def _version_tuple(version: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _validate_discovery(payload: dict[str, Any], *, root: Path, release: str) -> None:
    summary = payload.get("summary") or {}
    results = payload.get("results") or []
    digest = _corpus_digest(root)
    if payload.get("schema_version") != 1:
        raise EvidencePromotionError("discovery evidence schema_version must be 1")
    if payload.get("corpus") != _CORPUS.as_posix() and (_version_tuple(release) or (0, 0, 0)) >= (
        0,
        7,
        0,
    ):
        raise EvidencePromotionError(
            "0.7+ discovery evidence must contain only the canonical relative corpus path"
        )
    if payload.get("corpus_sha256") != digest:
        raise EvidencePromotionError(
            "discovery evidence corpus SHA-256 does not match committed corpus"
        )
    if payload.get("corpus_revision_policy") != "explicit-arxiv-vN":
        raise EvidencePromotionError(
            "discovery evidence must use explicit-arxiv-vN revision policy"
        )
    # The five-paper corpus is historical 0.5 evidence only. 0.6+ uses the
    # pinned 15-paper corpus, including 0.7 where discovery/runtime source has
    # changed and must be measured again instead of borrowing 0.6 evidence.
    expected_cases = 5 if release.startswith("0.5.") else 15
    required_summary = {
        "cases": expected_cases,
        "expected_repository_found": expected_cases,
        "top1": expected_cases,
        "evidence_anchored": expected_cases,
        "source_evaluable": expected_cases,
        "found_rate": 1.0,
        "top1_rate": 1.0,
        "evidence_anchor_rate": 1.0,
        "algorithm_found_rate": 1.0,
        "algorithm_top1_rate": 1.0,
        "algorithm_evidence_anchor_rate": 1.0,
    }
    for key, expected in required_summary.items():
        if summary.get(key) != expected:
            raise EvidencePromotionError(
                f"discovery evidence requires summary.{key}={expected!r}, got {summary.get(key)!r}"
            )
    if len(results) != expected_cases:
        raise EvidencePromotionError(
            f"discovery evidence must contain {expected_cases} per-case results"
        )
    for item in results:
        if not isinstance(item, dict):
            raise EvidencePromotionError("discovery evidence result must be an object")
        if item.get("discovery_status") != "ok":
            raise EvidencePromotionError(
                f"discovery case is not source-evaluable: {item.get('id')}"
            )
        if (
            item.get("found") is not True
            or item.get("rank") != 1
            or item.get("evidence_anchored") is not True
        ):
            raise EvidencePromotionError(
                f"discovery case did not pass found/top1/evidence gate: {item.get('id')}"
            )
        if not _PINNED_ARXIV_SOURCE.fullmatch(str(item.get("source") or "")):
            raise EvidencePromotionError(f"discovery case source is not pinned: {item.get('id')}")


def _validate_planning(payload: dict[str, Any], *, root: Path, release: str) -> None:
    summary = payload.get("summary") or {}
    results = payload.get("results") or []
    digest = _corpus_digest(root)
    if payload.get("schema_version") != 1:
        raise EvidencePromotionError("environment-planning evidence schema_version must be 1")
    if payload.get("corpus") != _CORPUS.as_posix() and (_version_tuple(release) or (0, 0, 0)) >= (
        0,
        7,
        0,
    ):
        raise EvidencePromotionError(
            "0.7+ planning evidence must contain only the canonical relative corpus path"
        )
    if payload.get("corpus_sha256") != digest:
        raise EvidencePromotionError(
            "environment-planning corpus SHA-256 does not match committed corpus"
        )
    if summary.get("cases") != 3:
        raise EvidencePromotionError(
            "environment-planning evidence must contain the bounded 3-case gate"
        )
    statuses = summary.get("repository_inspection_status") or {}
    if statuses.get("planned") != 3:
        raise EvidencePromotionError(
            "environment-planning evidence requires 3/3 planned repositories"
        )
    if len(results) != 3:
        raise EvidencePromotionError(
            "environment-planning evidence must contain 3 per-case results"
        )
    for item in results:
        inspection = (item or {}).get("repository_inspection") if isinstance(item, dict) else None
        if not isinstance(inspection, dict) or inspection.get("status") != "planned":
            raise EvidencePromotionError(
                f"environment-planning case did not plan: {(item or {}).get('id') if isinstance(item, dict) else None}"
            )
        if not inspection.get("commit_sha"):
            raise EvidencePromotionError(
                f"environment-planning case lacks pinned commit: {item.get('id')}"
            )


def _provenance(
    *,
    run_id: str,
    head_sha: str,
    artifact_id: str | None,
    artifact_digest: str | None,
) -> dict[str, Any]:
    normalized_run_id = run_id.strip()
    normalized_head = head_sha.strip().lower()
    if not _DECIMAL_ID.fullmatch(normalized_run_id):
        raise EvidencePromotionError("GitHub Actions run ID must be a positive decimal integer")
    if not _SHA40.fullmatch(normalized_head):
        raise EvidencePromotionError("head SHA must be a 40-character Git commit SHA")
    provenance: dict[str, Any] = {
        "github_actions_run_id": normalized_run_id,
        "head_sha": normalized_head,
    }
    if artifact_id is not None:
        normalized_artifact_id = artifact_id.strip()
        if not _DECIMAL_ID.fullmatch(normalized_artifact_id):
            raise EvidencePromotionError("artifact ID must be a positive decimal integer")
        provenance["artifact_id"] = normalized_artifact_id
    if artifact_digest is not None:
        normalized_digest = artifact_digest.strip().lower()
        if not _SHA256_DIGEST.fullmatch(normalized_digest):
            raise EvidencePromotionError(
                "artifact digest must be sha256 followed by 64 hexadecimal characters"
            )
        provenance["artifact_digest"] = normalized_digest
    return provenance


def _measurement_provenance(payload: dict[str, Any], *, label: str) -> dict[str, str]:
    raw = payload.get("measurement_provenance")
    if not isinstance(raw, dict):
        raise EvidencePromotionError(f"{label} must include measurement_provenance")
    workflow = raw.get("workflow")
    run_id = str(raw.get("github_actions_run_id") or "").strip()
    head_sha = str(raw.get("head_sha") or "").strip().lower()
    if workflow != "VeriRepro validation":
        raise EvidencePromotionError(
            f"{label} measurement_provenance workflow must be 'VeriRepro validation'"
        )
    if not _DECIMAL_ID.fullmatch(run_id):
        raise EvidencePromotionError(
            f"{label} measurement run id must be a positive decimal integer"
        )
    if not _SHA40.fullmatch(head_sha):
        raise EvidencePromotionError(f"{label} measurement head SHA must be a 40-character Git SHA")
    return {
        "workflow": "VeriRepro validation",
        "github_actions_run_id": run_id,
        "head_sha": head_sha,
    }


def _normalized_copy(
    payload: dict[str, Any],
    *,
    release: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    result = deepcopy(payload)
    result["release"] = release
    result["corpus"] = _CORPUS.as_posix()
    result["provenance"] = provenance
    return result


def promote_evidence(
    *,
    discovery_path: Path,
    planning_path: Path,
    release: str,
    run_id: str,
    head_sha: str,
    root: Path = ROOT,
    artifact_id: str | None = None,
    artifact_digest: str | None = None,
) -> tuple[Path, Path]:
    project_version = _project_version(root)
    if release != project_version:
        raise EvidencePromotionError(
            f"release {release!r} does not match pyproject version {project_version!r}"
        )
    discovery = _load_json(discovery_path)
    planning = _load_json(planning_path)
    _validate_discovery(discovery, root=root, release=release)
    _validate_planning(planning, root=root, release=release)
    provenance = _provenance(
        run_id=run_id,
        head_sha=head_sha,
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
    )

    version = _version_tuple(release)
    if version is not None and version >= (0, 7, 0):
        discovery_measurement = _measurement_provenance(discovery, label="discovery evidence")
        planning_measurement = _measurement_provenance(
            planning, label="environment-planning evidence"
        )
        if discovery_measurement != planning_measurement:
            raise EvidencePromotionError(
                "discovery and planning evidence must come from the same trusted measurement run/head"
            )
        expected_measurement = {
            "workflow": "VeriRepro validation",
            "github_actions_run_id": provenance["github_actions_run_id"],
            "head_sha": provenance["head_sha"],
        }
        if discovery_measurement != expected_measurement:
            raise EvidencePromotionError(
                "promotion run/head must exactly match measurement-time provenance; stale evidence cannot be relabeled"
            )

    discovery_output = root / f"benchmarks/real-paper-smoke-results-{release}.json"
    planning_output = root / f"benchmarks/environment-planning-results-{release}.json"
    discovery_output.write_text(
        json.dumps(
            _normalized_copy(discovery, release=release, provenance=provenance),
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    planning_output.write_text(
        json.dumps(
            _normalized_copy(planning, release=release, provenance=provenance),
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return discovery_output, planning_output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate trusted Actions outputs and promote them to versioned VeriRepro release evidence."
    )
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--planning", type=Path, required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--artifact-id")
    parser.add_argument("--artifact-digest")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    discovery_output, planning_output = promote_evidence(
        discovery_path=args.discovery,
        planning_path=args.planning,
        release=args.release,
        run_id=args.run_id,
        head_sha=args.head_sha,
        root=args.root,
        artifact_id=args.artifact_id,
        artifact_digest=args.artifact_digest,
    )
    print(f"Recorded: {discovery_output}")
    print(f"Recorded: {planning_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
