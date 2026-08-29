from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from reproagent import __version__
from reproagent.config import ArtifactSpec
from reproagent.release_provenance import release_source_sha256
from reproagent.reprobench_adapter import (
    ReproBenchContractError,
    load_reprobench_task,
    run_reprobench_task,
    write_reprobench_result,
)
from reproagent.reprobench_summary import (
    summarize_reprobench_results,
    write_reprobench_summary,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "benchmarks/reprobench-seed-suite.json"
DEFAULT_OUTPUT = ROOT / ".verirepro/benchmarks/reprobench-seed"
SCIENTIFIC_REFERENCE_ROOT = ROOT / "benchmarks/reprobench-reference"
_MAX_SUITE_BYTES = 256 * 1024
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_GATE_KEYS = frozenset(
    {
        "outcome",
        "environment_build_status",
        "experiment_execution_status",
        "intervention_count",
        "failure_taxonomy",
    }
)
_ALLOWED_CASE_KEYS = frozenset(
    {
        "task",
        "repository",
        "repository_ref",
        "command",
        "use_llm",
        "allow_network",
        "trust_repository_contract",
        "scientific_artifacts",
        "timeout_seconds",
        "release_gate",
    }
)


class SeedSuiteError(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise SeedSuiteError(f"non-finite JSON number is not allowed: {value}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_suite(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink():
        raise SeedSuiteError("seed suite must not be a symlink")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SeedSuiteError(f"could not read seed suite: {exc}") from exc
    if len(raw) > _MAX_SUITE_BYTES:
        raise SeedSuiteError(f"seed suite exceeds {_MAX_SUITE_BYTES} bytes")
    try:
        payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SeedSuiteError(f"invalid seed suite JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SeedSuiteError("seed suite must be an object with schema_version=1")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases or len(cases) > 10:
        raise SeedSuiteError("seed suite must contain 1-10 cases")
    return payload, hashlib.sha256(raw).hexdigest()


def _relative_task_path(raw: object) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise SeedSuiteError("seed case task must be a relative path")
    value = raw.replace("\\", "/")
    if value.startswith("/") or value.startswith("../") or "/../" in f"/{value}":
        raise SeedSuiteError("seed case task must stay inside the VeriRepro project")

    candidate = ROOT / value
    current = ROOT
    for part in Path(value).parts:
        if part in {"", "."}:
            continue
        current = current / part
        if current.is_symlink():
            raise SeedSuiteError("seed case task path must not contain symlinks")

    path = candidate.resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SeedSuiteError("seed case task escapes the VeriRepro project") from exc
    # Return the unresolved in-project path so load_reprobench_task retains its
    # own regular-file/symlink checks instead of receiving a dereferenced target.
    return candidate


def _bounded_string(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SeedSuiteError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result) > limit or "\x00" in result:
        raise SeedSuiteError(f"{field} exceeds its trusted harness bound")
    return result


def _optional_repository_ref(case: dict[str, Any], *, require_pinned: bool) -> str | None:
    value = case.get("repository_ref")
    if value is None:
        if require_pinned:
            raise SeedSuiteError(
                "canonical seed cases must pin repository_ref to a 40-character commit SHA"
            )
        return None
    result = _bounded_string(value, "repository_ref", 200)
    if require_pinned and not _GIT_SHA.fullmatch(result):
        raise SeedSuiteError(
            "canonical seed repository_ref must be a 40-character lowercase commit SHA"
        )
    return result


def _bool(case: dict[str, Any], key: str, default: bool = False) -> bool:
    value = case.get(key, default)
    if not isinstance(value, bool):
        raise SeedSuiteError(f"{key} must be boolean")
    return value


def _timeout(case: dict[str, Any]) -> int:
    value = case.get("timeout_seconds", 300)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1800:
        raise SeedSuiteError("timeout_seconds must be an integer in [1, 1800]")
    return value


def _finite(value: object, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SeedSuiteError(f"{field} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise SeedSuiteError(f"{field} must be a finite number")
    return parsed


def _trusted_scientific_artifacts(
    case: dict[str, Any],
) -> tuple[tuple[ArtifactSpec, ...], list[dict[str, str]]]:
    raw_specs = case.get("scientific_artifacts", [])
    if not isinstance(raw_specs, list) or len(raw_specs) > 16:
        raise SeedSuiteError("scientific_artifacts must be a list with at most 16 entries")
    allowed = {
        "name",
        "kind",
        "reference",
        "reproduced",
        "threshold",
        "absolute_tolerance",
        "relative_tolerance",
        "columns",
    }
    specs: list[ArtifactSpec] = []
    references: list[dict[str, str]] = []
    seen_references: set[str] = set()
    for index, raw in enumerate(raw_specs):
        if not isinstance(raw, dict):
            raise SeedSuiteError(f"scientific_artifacts[{index}] must be an object")
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise SeedSuiteError(
                f"scientific_artifacts[{index}] contains unsupported keys: {unknown}"
            )
        name = _bounded_string(raw.get("name"), f"scientific_artifacts[{index}].name", 200)
        kind = _bounded_string(raw.get("kind"), f"scientific_artifacts[{index}].kind", 20).lower()
        if kind not in {"figure", "table", "file"}:
            raise SeedSuiteError(f"scientific_artifacts[{index}].kind is unsupported")
        reference = _bounded_string(
            raw.get("reference"), f"scientific_artifacts[{index}].reference", 512
        ).replace("\\", "/")
        reproduced = _bounded_string(
            raw.get("reproduced"), f"scientific_artifacts[{index}].reproduced", 512
        ).replace("\\", "/")
        if (
            reference.startswith("/")
            or reference.startswith("../")
            or "/../" in f"/{reference}"
            or reproduced.startswith("/")
            or reproduced.startswith("../")
            or "/../" in f"/{reproduced}"
        ):
            raise SeedSuiteError("scientific artifact paths must be confined relative paths")
        reference_path = SCIENTIFIC_REFERENCE_ROOT / reference
        if reference_path.is_symlink() or not reference_path.is_file():
            raise SeedSuiteError(f"scientific artifact reference is missing or unsafe: {reference}")
        resolved = reference_path.resolve()
        try:
            resolved.relative_to(SCIENTIFIC_REFERENCE_ROOT.resolve())
        except ValueError as exc:
            raise SeedSuiteError("scientific artifact reference escapes benchmark root") from exc
        threshold = _finite(raw.get("threshold", 0.95), "scientific artifact threshold")
        absolute = _finite(
            raw.get("absolute_tolerance", 1e-6), "scientific artifact absolute_tolerance"
        )
        relative = _finite(
            raw.get("relative_tolerance", 0.01), "scientific artifact relative_tolerance"
        )
        if not 0.0 <= threshold <= 1.0 or absolute < 0 or relative < 0:
            raise SeedSuiteError("scientific artifact thresholds/tolerances are out of range")
        raw_columns = raw.get("columns", [])
        if not isinstance(raw_columns, list) or len(raw_columns) > 128:
            raise SeedSuiteError("scientific artifact columns must be a bounded list")
        columns = tuple(str(value).strip() for value in raw_columns)
        if any(not value or len(value) > 200 for value in columns) or len(set(columns)) != len(
            columns
        ):
            raise SeedSuiteError("scientific artifact columns must be unique bounded names")
        if columns and kind != "table":
            raise SeedSuiteError("scientific artifact column selection requires kind=table")
        specs.append(
            ArtifactSpec(
                name=name,
                kind=kind,
                reference=reference,
                reproduced=reproduced,
                threshold=threshold,
                absolute_tolerance=absolute,
                relative_tolerance=relative,
                columns=columns,
            )
        )
        if reference not in seen_references:
            references.append(
                {
                    "file": f"benchmarks/reprobench-reference/{reference}",
                    "sha256": _sha256(reference_path),
                }
            )
            seen_references.add(reference)
    return tuple(specs), references


def _validate_gate(gate: object) -> dict[str, Any]:
    if not isinstance(gate, dict) or not gate:
        raise SeedSuiteError("release_gate must be a non-empty object")
    unknown = sorted(set(gate) - _ALLOWED_GATE_KEYS)
    if unknown:
        raise SeedSuiteError(f"release_gate contains unsupported keys: {unknown}")
    return gate


def _gate_result(payload: dict[str, Any], gate: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    measurements = payload.get("measurements") or {}
    mapping = {
        "outcome": payload.get("outcome"),
        "environment_build_status": measurements.get("environment_build_status"),
        "experiment_execution_status": measurements.get("experiment_execution_status"),
        "intervention_count": payload.get("intervention_count"),
        "failure_taxonomy": payload.get("failure_taxonomy"),
    }
    for key, expected in gate.items():
        actual = mapping[key]
        if actual != expected:
            failures.append(f"{key}: expected {expected!r}, got {actual!r}")
    return failures


def _provenance() -> dict[str, str | None]:
    return {
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "github_actions_run_id": os.environ.get("GITHUB_RUN_ID"),
        "head_sha": os.environ.get("VERIREPRO_SOURCE_SHA") or os.environ.get("GITHUB_SHA"),
    }


def run_seed_suite(suite_path: Path, output_dir: Path) -> dict[str, Any]:
    suite, suite_sha256 = _load_suite(suite_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_paths: list[Path] = []
    case_records: list[dict[str, Any]] = []
    task_ids: set[str] = set()
    canonical_suite = suite_path.resolve() == DEFAULT_SUITE.resolve()

    for index, raw_case in enumerate(suite["cases"], start=1):
        if not isinstance(raw_case, dict):
            raise SeedSuiteError(f"seed case {index} must be an object")
        unknown = sorted(set(raw_case) - _ALLOWED_CASE_KEYS)
        if unknown:
            raise SeedSuiteError(f"seed case {index} contains unsupported keys: {unknown}")

        task_path = _relative_task_path(raw_case.get("task"))
        try:
            task = load_reprobench_task(task_path)
        except ReproBenchContractError as exc:
            raise SeedSuiteError(f"invalid task for seed case {index}: {exc}") from exc
        if task.task_id in task_ids:
            raise SeedSuiteError(f"duplicate task_id in seed suite: {task.task_id}")
        task_ids.add(task.task_id)

        repository = _bounded_string(raw_case.get("repository"), "repository", 4096)
        repository_ref = _optional_repository_ref(raw_case, require_pinned=canonical_suite)
        command = _bounded_string(raw_case.get("command"), "command", 1000)
        use_llm = _bool(raw_case, "use_llm")
        allow_network = _bool(raw_case, "allow_network")
        trust_contract = _bool(raw_case, "trust_repository_contract")
        scientific_artifacts, scientific_references = _trusted_scientific_artifacts(raw_case)
        gate = _validate_gate(raw_case.get("release_gate"))
        timeout = _timeout(raw_case)

        result = run_reprobench_task(
            task,
            workspace_root=output_dir / "workspaces" / task.task_id,
            repository_url=repository,
            repository_ref=repository_ref,
            command=command,
            execute=True,
            timeout=timeout,
            use_llm=use_llm,
            allow_network=allow_network,
            trust_repository_contract=True if trust_contract else None,
            trusted_artifact_contract=scientific_artifacts,
            trusted_reference_root=SCIENTIFIC_REFERENCE_ROOT if scientific_artifacts else None,
        )
        result_path = output_dir / "results" / f"{task.task_id}.json"
        write_reprobench_result(result, result_path)
        result_paths.append(result_path)
        result_payload = result.to_dict()
        gate_failures = _gate_result(result_payload, gate)
        case_records.append(
            {
                "task_id": task.task_id,
                "task_file": task_path.relative_to(ROOT).as_posix(),
                "task_sha256": _sha256(task_path),
                "result_file": result_path.relative_to(output_dir).as_posix(),
                "result_sha256": _sha256(result_path),
                "repository_ref": repository_ref,
                "scientific_references": scientific_references,
                "gate_passed": not gate_failures,
                "gate_failures": gate_failures,
            }
        )

    summary = summarize_reprobench_results(result_paths)
    summary_path = write_reprobench_summary(summary, output_dir / "summary.json")
    manifest = {
        "schema_version": 1,
        "release": __version__,
        "suite": suite_path.relative_to(ROOT).as_posix(),
        "suite_sha256": suite_sha256,
        "source_tree_sha256": release_source_sha256(ROOT),
        "cases": case_records,
        "summary_file": summary_path.relative_to(output_dir).as_posix(),
        "summary_sha256": _sha256(summary_path),
        "gate_passed": all(record["gate_passed"] for record in case_records),
        "provenance": _provenance(),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the trusted VeriRepro ReproBench seed suite. Third-party code executes only "
            "through the normal Docker reproduction boundary; suite overrides are recorded as interventions."
        )
    )
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    manifest = run_seed_suite(args.suite, args.output)
    for case in manifest["cases"]:
        print(
            f"Seed {case['task_id']}: gate={'PASS' if case['gate_passed'] else 'FAIL'} "
            f"failures={case['gate_failures']}"
        )
    print(
        f"Release={manifest['release']} suite_sha256={manifest['suite_sha256']} "
        f"source_tree_sha256={manifest['source_tree_sha256']} "
        f"summary_sha256={manifest['summary_sha256']}"
    )
    print(f"Summary: {manifest['summary_file']}")
    return 0 if manifest["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
