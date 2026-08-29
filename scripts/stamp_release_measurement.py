from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_CANONICAL_CORPUS = Path("benchmarks/real-paper-smoke.json")
_MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_DECIMAL_ID = re.compile(r"^[1-9][0-9]*$")


class MeasurementStampError(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise MeasurementStampError(f"non-finite JSON number is not allowed: {value}")


def _canonical_corpus_sha256(root: Path) -> str:
    return hashlib.sha256((root / _CANONICAL_CORPUS).read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise MeasurementStampError("measurement evidence must be a regular non-symlink file")
    size = path.stat().st_size
    if size > _MAX_EVIDENCE_BYTES:
        raise MeasurementStampError(
            f"measurement evidence exceeds {_MAX_EVIDENCE_BYTES} byte safety limit ({size} bytes)"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MeasurementStampError(f"could not parse measurement evidence: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise MeasurementStampError("measurement evidence must be a schema_version=1 JSON object")
    return payload


def _trusted_provenance(source_sha: str) -> dict[str, str]:
    normalized_sha = source_sha.strip().lower()
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    workflow = os.environ.get("GITHUB_WORKFLOW", "").strip()
    if not _GIT_SHA.fullmatch(normalized_sha):
        raise MeasurementStampError("source SHA must be a 40-character lowercase Git SHA")
    if not _DECIMAL_ID.fullmatch(run_id):
        raise MeasurementStampError("GITHUB_RUN_ID must be a positive decimal integer")
    if workflow != "VeriRepro validation":
        raise MeasurementStampError(
            "trusted release measurement must run in the 'VeriRepro validation' workflow"
        )
    return {
        "workflow": workflow,
        "github_actions_run_id": run_id,
        "head_sha": normalized_sha,
    }


def stamp_measurement(
    path: Path,
    *,
    source_sha: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Sanitize and bind one trusted front-half measurement to its exact run/head.

    The real-paper runner is also useful locally, where its input corpus may be
    an arbitrary path. Release artifacts are different: they must bind the
    committed canonical corpus bytes and must never redistribute a maintainer
    host path. This post-measurement step is invoked only by trusted release CI.
    """
    payload = _load_json(path)
    canonical_digest = _canonical_corpus_sha256(root)
    if payload.get("corpus_sha256") != canonical_digest:
        raise MeasurementStampError(
            "measurement corpus SHA-256 does not match the committed release corpus"
        )
    if payload.get("corpus_revision_policy") != "explicit-arxiv-vN":
        raise MeasurementStampError(
            "measurement evidence must use the explicit-arxiv-vN revision policy"
        )

    payload["corpus"] = _CANONICAL_CORPUS.as_posix()
    payload["measurement_provenance"] = _trusted_provenance(source_sha)

    encoded = json.dumps(payload, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(f".{path.name}.stamped")
    try:
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sanitize a trusted real-paper/planning measurement and bind it to "
            "the exact GitHub Actions run and source head that produced it."
        )
    )
    parser.add_argument("evidence", type=Path)
    parser.add_argument(
        "--source-sha",
        default=os.environ.get("VERIREPRO_SOURCE_SHA", ""),
        help="exact measured source SHA (normally VERIREPRO_SOURCE_SHA from trusted CI)",
    )
    args = parser.parse_args()
    try:
        payload = stamp_measurement(args.evidence, source_sha=args.source_sha)
    except MeasurementStampError as exc:
        print(f"FAIL: {exc}")
        return 1
    provenance = payload["measurement_provenance"]
    print(
        "PASS: stamped trusted measurement "
        f"run={provenance['github_actions_run_id']} head={provenance['head_sha']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
