from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from reproagent.release_provenance import release_source_sha256

ROOT = Path(__file__).resolve().parents[1]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_DECIMAL_ID = re.compile(r"^[1-9][0-9]*$")


def _json_object(path: Path, *, label: str, errors: list[str]) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        errors.append(f"missing safe {label}: {path}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"could not parse {label}: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label} must contain a JSON object")
        return None
    return payload


def _measurement_identity(
    payload: dict[str, Any], *, label: str, errors: list[str]
) -> tuple[str, str] | None:
    provenance = payload.get("measurement_provenance")
    if not isinstance(provenance, dict):
        errors.append(f"{label} must include measurement_provenance")
        return None
    if provenance.get("workflow") != "VeriRepro validation":
        errors.append(f"{label} measurement workflow must be 'VeriRepro validation'")
    run_id = str(provenance.get("github_actions_run_id") or "").strip()
    head_sha = str(provenance.get("head_sha") or "").strip().lower()
    if not _DECIMAL_ID.fullmatch(run_id):
        errors.append(f"{label} measurement run id must be a positive decimal integer")
        return None
    if not _GIT_SHA.fullmatch(head_sha):
        errors.append(f"{label} measurement head SHA must be a 40-character Git SHA")
        return None
    return run_id, head_sha


def _promotion_identity(
    payload: dict[str, Any], *, label: str, errors: list[str]
) -> tuple[str, str] | None:
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        errors.append(f"{label} must include promotion provenance")
        return None
    run_id = str(provenance.get("github_actions_run_id") or "").strip()
    head_sha = str(provenance.get("head_sha") or "").strip().lower()
    if not _DECIMAL_ID.fullmatch(run_id):
        errors.append(f"{label} promotion run id must be a positive decimal integer")
        return None
    if not _GIT_SHA.fullmatch(head_sha):
        errors.append(f"{label} promotion head SHA must be a 40-character Git SHA")
        return None
    return run_id, head_sha


def _reprobench_identity(
    manifest: dict[str, Any], *, errors: list[str]
) -> tuple[str, str] | None:
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("ReproBench release manifest must include trusted provenance")
        return None
    if provenance.get("workflow") != "VeriRepro validation":
        errors.append("ReproBench provenance workflow must be 'VeriRepro validation'")
    run_id = str(provenance.get("github_actions_run_id") or "").strip()
    head_sha = str(provenance.get("head_sha") or "").strip().lower()
    if not _DECIMAL_ID.fullmatch(run_id):
        errors.append("ReproBench provenance run id must be a positive decimal integer")
        return None
    if not _GIT_SHA.fullmatch(head_sha):
        errors.append("ReproBench provenance head SHA must be a 40-character Git SHA")
        return None
    return run_id, head_sha


def _check_cross_evidence_identity(
    root: Path,
    *,
    version: str,
    manifest: dict[str, Any],
    errors: list[str],
) -> None:
    """Require every promoted 0.7+ evidence family to name one trusted run/head.

    `release_check.py` owns presence/shape/semantic validation for each evidence
    family. This source-integrity checker independently proves that the two
    front-half measurements, their promotion records, and the ReproBench bundle
    all refer to the same exact trusted source execution. Missing front-half
    files are left to `release_check.py`; when present they must be consistent.
    """
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match or tuple(int(part) for part in match.groups()) < (0, 7, 0):
        return

    discovery_path = root / f"benchmarks/real-paper-smoke-results-{version}.json"
    planning_path = root / f"benchmarks/environment-planning-results-{version}.json"
    if not discovery_path.is_file() or not planning_path.is_file():
        return

    discovery = _json_object(
        discovery_path, label="real-paper release evidence", errors=errors
    )
    planning = _json_object(
        planning_path, label="environment-planning release evidence", errors=errors
    )
    if discovery is None or planning is None:
        return

    discovery_measurement = _measurement_identity(
        discovery, label="real-paper release evidence", errors=errors
    )
    planning_measurement = _measurement_identity(
        planning, label="environment-planning release evidence", errors=errors
    )
    discovery_promotion = _promotion_identity(
        discovery, label="real-paper release evidence", errors=errors
    )
    planning_promotion = _promotion_identity(
        planning, label="environment-planning release evidence", errors=errors
    )
    reprobench = _reprobench_identity(manifest, errors=errors)

    if discovery_measurement and planning_measurement and discovery_measurement != planning_measurement:
        errors.append("discovery and planning measurement provenance must use the same trusted run/head")
    if discovery_measurement and discovery_promotion and discovery_measurement != discovery_promotion:
        errors.append("real-paper promotion provenance must match its measurement-time run/head")
    if planning_measurement and planning_promotion and planning_measurement != planning_promotion:
        errors.append("planning promotion provenance must match its measurement-time run/head")
    if discovery_measurement and reprobench and discovery_measurement != reprobench:
        errors.append("front-half and ReproBench evidence must come from the same trusted run/head")


def check_release_source(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        version = str(project["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        return [f"could not resolve project version: {exc}"]

    manifest_path = root / f"benchmarks/reprobench-results-{version}/manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return [f"missing safe release evidence manifest: {manifest_path.relative_to(root)}"]

    manifest = _json_object(
        manifest_path, label="release evidence manifest", errors=errors
    )
    if manifest is None:
        return errors

    if manifest.get("release") != version:
        errors.append("release evidence manifest version must match pyproject version")

    expected = manifest.get("source_tree_sha256")
    if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
        errors.append("release evidence manifest must contain source_tree_sha256")
        return errors

    try:
        actual = release_source_sha256(root)
    except (OSError, ValueError) as exc:
        errors.append(f"could not fingerprint release source: {exc}")
        return errors
    if actual != expected:
        errors.append(
            "release-relevant source bytes changed after benchmark evidence was produced: "
            f"expected {expected}, got {actual}"
        )

    _check_cross_evidence_identity(
        root,
        version=version,
        manifest=manifest,
        errors=errors,
    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that versioned release evidence was produced from the current "
            "release-relevant source bytes and one consistent trusted run/head."
        )
    )
    parser.parse_args()
    errors = check_release_source()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "PASS: release evidence source fingerprint and trusted run/head identity "
        "match the current release tree"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())