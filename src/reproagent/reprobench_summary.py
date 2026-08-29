from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .reprobench_adapter import REPROBENCH_RESULT_SCHEMA_VERSION, REPROBENCH_TASK_SCHEMA_VERSION

REPROBENCH_SUMMARY_SCHEMA_VERSION = 1
_MAX_RESULT_BYTES = 5 * 1024 * 1024
_VALID_OUTCOMES = frozenset({"success", "partial", "failure"})
_VALID_STAGE_STATUSES = frozenset({"passed", "failed", "skipped"})
_SOFT_PARTIAL_TAXONOMY = "insufficient_evidence_or_execution"
_MODEL_USAGE_INTEGER_FIELDS = (
    "calls_with_telemetry",
    "request_count",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
    "reasoning_tokens",
)


class ReproBenchSummaryError(ValueError):
    """Raised when benchmark result evidence is malformed or ambiguous."""


def _reject_constant(value: str) -> None:
    raise ReproBenchSummaryError(f"non-finite JSON number is not allowed: {value}")


def _load_result(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink():
        raise ReproBenchSummaryError(f"result file must not be a symlink: {path.name}")
    try:
        stat = path.stat()
    except OSError as exc:
        raise ReproBenchSummaryError(f"could not stat result {path.name}: {exc}") from exc
    if not path.is_file():
        raise ReproBenchSummaryError(f"result must be a regular JSON file: {path.name}")
    if stat.st_size > _MAX_RESULT_BYTES:
        raise ReproBenchSummaryError(
            f"result exceeds the {_MAX_RESULT_BYTES}-byte aggregation limit: {path.name}"
        )
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReproBenchSummaryError(f"invalid result JSON {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReproBenchSummaryError(f"result JSON must contain an object: {path.name}")
    return payload, hashlib.sha256(raw).hexdigest()


def _finite_number(value: object, field: str, *, minimum: float | None = None) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ReproBenchSummaryError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ReproBenchSummaryError(f"{field} must be finite")
    if minimum is not None and result < minimum:
        raise ReproBenchSummaryError(f"{field} must be >= {minimum}")
    return result


def _nonnegative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReproBenchSummaryError(f"{field} must be a non-negative integer")
    return value


def _string_list(value: object, field: str, *, unique: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ReproBenchSummaryError(f"{field} must be a list of non-empty strings")
    if unique and len(set(value)) != len(value):
        raise ReproBenchSummaryError(f"{field} must not contain duplicates")
    return list(value)


def _validate_outcome_taxonomy(outcome: str, taxonomy: list[str], filename: str) -> None:
    """Reject result evidence that downgrades or obscures failure semantics."""
    if outcome == "success":
        if taxonomy:
            raise ReproBenchSummaryError(
                f"successful result must not declare failure taxonomy entries: {filename}"
            )
        return
    if outcome == "partial":
        if taxonomy != [_SOFT_PARTIAL_TAXONOMY]:
            raise ReproBenchSummaryError(
                "partial result must declare exactly the soft "
                f"{_SOFT_PARTIAL_TAXONOMY!r} taxonomy entry: {filename}"
            )
        return
    if not taxonomy or _SOFT_PARTIAL_TAXONOMY in taxonomy:
        raise ReproBenchSummaryError(
            "failure result must declare one or more hard failure taxonomy entries "
            f"and must not use the partial-only {_SOFT_PARTIAL_TAXONOMY!r} entry: {filename}"
        )


def _validate_result(payload: dict[str, Any], filename: str) -> dict[str, Any]:
    if payload.get("schema_version") != REPROBENCH_RESULT_SCHEMA_VERSION:
        raise ReproBenchSummaryError(
            f"unsupported result schema_version in {filename}: {payload.get('schema_version')!r}"
        )
    if payload.get("benchmark") != "reprobench":
        raise ReproBenchSummaryError(f"result benchmark must be 'reprobench': {filename}")
    task = payload.get("task")
    if not isinstance(task, dict):
        raise ReproBenchSummaryError(f"result task must be an object: {filename}")
    if task.get("schema_version") != REPROBENCH_TASK_SCHEMA_VERSION:
        raise ReproBenchSummaryError(f"unsupported task schema_version in result: {filename}")
    task_id = task.get("task_id")
    domain = task.get("domain")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ReproBenchSummaryError(f"result task_id is missing: {filename}")
    if not isinstance(domain, str) or not domain.strip():
        raise ReproBenchSummaryError(f"result domain is missing: {filename}")
    outcome = payload.get("outcome")
    if outcome not in _VALID_OUTCOMES:
        raise ReproBenchSummaryError(f"invalid outcome in {filename}: {outcome!r}")
    _finite_number(
        payload.get("wall_clock_seconds"),
        f"{filename}.wall_clock_seconds",
        minimum=0.0,
    )
    if not isinstance(payload.get("execution_requested"), bool):
        raise ReproBenchSummaryError(f"execution_requested must be boolean: {filename}")

    interventions = _string_list(
        payload.get("operator_interventions"),
        f"{filename}.operator_interventions",
        unique=True,
    )
    intervention_count = _nonnegative_int(
        payload.get("intervention_count"), f"{filename}.intervention_count"
    )
    if intervention_count != len(interventions):
        raise ReproBenchSummaryError(
            f"intervention_count must equal operator_interventions length: {filename}"
        )

    measurements = payload.get("measurements")
    if not isinstance(measurements, dict):
        raise ReproBenchSummaryError(f"measurements must be an object: {filename}")
    taxonomy = _string_list(
        payload.get("failure_taxonomy"), f"{filename}.failure_taxonomy", unique=True
    )
    _validate_outcome_taxonomy(str(outcome), taxonomy, filename)

    stages = payload.get("stages")
    if not isinstance(stages, list):
        raise ReproBenchSummaryError(f"stages must be a list: {filename}")
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) != {"name", "status"}:
            raise ReproBenchSummaryError(
                f"benchmark stages must contain only name/status fields: {filename}"
            )
        if not isinstance(stage.get("name"), str) or not stage["name"]:
            raise ReproBenchSummaryError(f"stage name is invalid: {filename}")
        if stage.get("status") not in _VALID_STAGE_STATUSES:
            raise ReproBenchSummaryError(f"stage status is invalid: {filename}")

    agent = payload.get("agent")
    if (
        not isinstance(agent, dict)
        or not isinstance(agent.get("name"), str)
        or not agent.get("name")
        or not isinstance(agent.get("version"), str)
        or not agent.get("version")
    ):
        raise ReproBenchSummaryError(f"agent name/version metadata is missing: {filename}")
    return payload


def _optional_nonnegative_int(measurements: dict[str, Any], key: str) -> int | None:
    value = measurements.get(key)
    if value is None:
        return None
    return _nonnegative_int(value, f"measurements.{key}")


def _stage_rate(results: list[dict[str, Any]], measurement: str) -> dict[str, Any]:
    statuses = Counter(
        str((item.get("measurements") or {}).get(measurement))
        for item in results
        if (item.get("measurements") or {}).get(measurement) is not None
    )
    invalid = sorted(set(statuses) - _VALID_STAGE_STATUSES)
    if invalid:
        raise ReproBenchSummaryError(
            f"{measurement} contains invalid stage status values: {invalid}"
        )
    attempted = statuses.get("passed", 0) + statuses.get("failed", 0)
    passed = statuses.get("passed", 0)
    return {
        "statuses": dict(sorted(statuses.items())),
        "attempted": attempted,
        "passed": passed,
        "pass_rate": passed / attempted if attempted else None,
    }


def _comparison_totals(
    results: list[dict[str, Any]], *, count_key: str, passed_key: str
) -> dict[str, Any]:
    total = 0
    passed = 0
    tasks_with_comparisons = 0
    for item in results:
        measurements = item.get("measurements") or {}
        count = _optional_nonnegative_int(measurements, count_key)
        passed_count = _optional_nonnegative_int(measurements, passed_key)
        if (count is None) != (passed_count is None):
            raise ReproBenchSummaryError(
                f"{count_key} and {passed_key} must either both be present or both be null"
            )
        if count is None:
            continue
        assert passed_count is not None
        if passed_count > count:
            raise ReproBenchSummaryError(f"{passed_key} cannot exceed {count_key}")
        total += count
        passed += passed_count
        tasks_with_comparisons += int(count > 0)
    return {
        "tasks_with_comparisons": tasks_with_comparisons,
        "comparisons": total,
        "passed": passed,
        "pass_rate": passed / total if total else None,
    }


def _expected_artifact_totals(results: list[dict[str, Any]]) -> dict[str, Any]:
    expected = 0
    found = 0
    tasks_with_expectations = 0
    for item in results:
        measurements = item.get("measurements") or {}
        declared = measurements.get("expected_artifacts")
        present = measurements.get("expected_artifacts_found")
        missing = measurements.get("expected_artifacts_missing")
        if declared is None and present is None and missing is None:
            continue
        declared_list = _string_list(declared, "measurements.expected_artifacts", unique=True)
        present_list = _string_list(present, "measurements.expected_artifacts_found", unique=True)
        missing_list = _string_list(missing, "measurements.expected_artifacts_missing", unique=True)
        declared_set = set(declared_list)
        present_set = set(present_list)
        missing_set = set(missing_list)
        if present_set & missing_set:
            raise ReproBenchSummaryError("expected artifacts cannot be both found and missing")
        if present_set | missing_set != declared_set:
            raise ReproBenchSummaryError(
                "expected artifact accounting must exactly partition declared artifacts into found/missing"
            )
        tasks_with_expectations += int(bool(declared_list))
        expected += len(declared_list)
        found += len(present_list)
    return {
        "tasks_with_expectations": tasks_with_expectations,
        "expected": expected,
        "found": found,
        "found_rate": found / expected if expected else None,
    }


def _model_usage_totals(results: list[dict[str, Any]]) -> dict[str, Any]:
    costs: list[float] = []
    token_snapshots: list[dict[str, Any]] = []
    for item in results:
        measurements = item.get("measurements") or {}
        cost = measurements.get("model_cost_usd")
        if cost is not None:
            costs.append(_finite_number(cost, "measurements.model_cost_usd", minimum=0.0))

        usage = measurements.get("token_usage")
        if usage is None:
            continue
        if not isinstance(usage, dict):
            raise ReproBenchSummaryError("measurements.token_usage must be an object or null")
        normalized: dict[str, Any] = {}
        for key in _MODEL_USAGE_INTEGER_FIELDS:
            value = usage.get(key)
            normalized[key] = (
                None
                if value is None
                else _nonnegative_int(value, f"measurements.token_usage.{key}")
            )
        duration = usage.get("duration_seconds")
        normalized["duration_seconds"] = (
            None
            if duration is None
            else _finite_number(
                duration,
                "measurements.token_usage.duration_seconds",
                minimum=0.0,
            )
        )
        token_snapshots.append(normalized)

    totals: dict[str, Any] = {
        "cases_with_cost": len(costs),
        "cost_usd_total": round(sum(costs), 10) if costs else None,
        "cases_with_token_usage": len(token_snapshots),
    }
    for key in _MODEL_USAGE_INTEGER_FIELDS:
        values = [value for usage in token_snapshots if isinstance((value := usage.get(key)), int)]
        totals[key] = sum(values) if values else None
    durations = [
        float(value)
        for usage in token_snapshots
        if isinstance((value := usage.get("duration_seconds")), (int, float))
    ]
    totals["duration_seconds"] = round(sum(durations), 6) if durations else None
    return totals


def summarize_reprobench_results(paths: Iterable[Path]) -> dict[str, Any]:
    ordered = sorted((Path(path) for path in paths), key=lambda item: item.name)
    if not ordered:
        raise ReproBenchSummaryError("at least one ReproBench result is required")

    results: list[dict[str, Any]] = []
    inputs: list[dict[str, str]] = []
    seen_task_ids: set[str] = set()
    for path in ordered:
        payload, digest = _load_result(path)
        validated = _validate_result(payload, path.name)
        task_id = str(validated["task"]["task_id"])
        if task_id in seen_task_ids:
            raise ReproBenchSummaryError(f"duplicate benchmark task_id: {task_id}")
        seen_task_ids.add(task_id)
        results.append(validated)
        inputs.append({"file": path.name, "sha256": digest, "task_id": task_id})

    outcomes = Counter(str(item["outcome"]) for item in results)
    failure_taxonomy = Counter(
        category for item in results for category in item.get("failure_taxonomy") or []
    )
    intervention_counts = [int(item["intervention_count"]) for item in results]
    wall_clock = [float(item["wall_clock_seconds"]) for item in results]
    zero_intervention = sum(value == 0 for value in intervention_counts)

    domains: dict[str, Counter[str]] = defaultdict(Counter)
    for item in results:
        domains[str(item["task"]["domain"])][str(item["outcome"])] += 1
    domain_summary = {
        domain: {
            "cases": sum(counts.values()),
            "outcomes": dict(sorted(counts.items())),
            "success_rate": counts.get("success", 0) / sum(counts.values()),
        }
        for domain, counts in sorted(domains.items())
    }

    agents = Counter(
        f"{(item.get('agent') or {}).get('name')}@{(item.get('agent') or {}).get('version')}"
        for item in results
    )
    count = len(results)
    return {
        "schema_version": REPROBENCH_SUMMARY_SCHEMA_VERSION,
        "benchmark": "reprobench",
        "result_schema_version": REPROBENCH_RESULT_SCHEMA_VERSION,
        "inputs": inputs,
        "summary": {
            "cases": count,
            "outcomes": dict(sorted(outcomes.items())),
            "success_rate": outcomes.get("success", 0) / count,
            "partial_rate": outcomes.get("partial", 0) / count,
            "failure_rate": outcomes.get("failure", 0) / count,
            "zero_intervention_cases": zero_intervention,
            "zero_intervention_rate": zero_intervention / count,
            "interventions_total": sum(intervention_counts),
            "wall_clock_seconds_total": round(sum(wall_clock), 6),
            "wall_clock_seconds_mean": round(statistics.fmean(wall_clock), 6),
            "wall_clock_seconds_median": round(statistics.median(wall_clock), 6),
            "environment_build": _stage_rate(results, "environment_build_status"),
            "experiment_execution": _stage_rate(results, "experiment_execution_status"),
            "grounded_metrics": _comparison_totals(
                results,
                count_key="grounded_metric_comparisons",
                passed_key="grounded_metric_passed",
            ),
            "artifact_comparisons": _comparison_totals(
                results,
                count_key="artifact_comparisons",
                passed_key="artifact_comparisons_passed",
            ),
            "expected_artifacts": _expected_artifact_totals(results),
            "model_usage": _model_usage_totals(results),
            "failure_taxonomy": dict(sorted(failure_taxonomy.items())),
            "domains": domain_summary,
            "agents": dict(sorted(agents.items())),
        },
    }


def write_reprobench_summary(payload: dict[str, Any], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verirepro-reprobench-summary",
        description="Deterministically aggregate versioned ReproBench result JSON files.",
    )
    parser.add_argument("results", type=Path, nargs="+", help="ReproBench result JSON files")
    parser.add_argument("--output", type=Path, default=Path("reprobench-summary.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = summarize_reprobench_results(args.results)
    output = write_reprobench_summary(payload, args.output)
    summary = payload["summary"]
    print(
        f"ReproBench summary: cases={summary['cases']} success={summary['success_rate']:.1%} "
        f"zero_intervention={summary['zero_intervention_rate']:.1%}"
    )
    print(f"Result: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
