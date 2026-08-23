from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .llm import capture_model_usage
from .models import REPORT_SCHEMA_VERSION, ReproductionReport
from .pipeline import reproduce
from .usage import aggregate_model_usage

REPROBENCH_TASK_SCHEMA_VERSION = 1
REPROBENCH_RESULT_SCHEMA_VERSION = 1
_MAX_TASK_BYTES = 1024 * 1024
_MAX_EXTRA_FIELDS = 64
_MAX_EXTRA_FIELD_NAME = 100
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_ARXIV_SOURCE = re.compile(r"^(?:arxiv:)?\d{4}\.\d{4,5}(?:v\d+)?$", re.IGNORECASE)
_DOI_SOURCE = re.compile(r"^(?:doi:)?10\.\d{4,9}/\S+$", re.IGNORECASE)
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:/")
_CORE_TASK_FIELDS = frozenset({"schema_version", "task_id", "domain", "paper", "expected_artifacts"})


class ReproBenchContractError(ValueError):
    """Raised when a benchmark task crosses or violates the adapter contract."""


@dataclass(frozen=True)
class ReproBenchTask:
    schema_version: int
    task_id: str
    domain: str
    paper: str
    expected_artifacts: tuple[str, ...]
    extra_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "domain": self.domain,
            "paper": self.paper,
            "expected_artifacts": list(self.expected_artifacts),
            "extra_fields": list(self.extra_fields),
        }


@dataclass(frozen=True)
class ReproBenchResult:
    schema_version: int
    benchmark: str
    task: ReproBenchTask
    agent: dict[str, Any]
    outcome: str
    wall_clock_seconds: float
    execution_requested: bool
    operator_interventions: tuple[str, ...]
    measurements: dict[str, Any]
    failure_taxonomy: tuple[str, ...]
    stages: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "task": self.task.to_dict(),
            "agent": dict(self.agent),
            "outcome": self.outcome,
            "wall_clock_seconds": self.wall_clock_seconds,
            "execution_requested": self.execution_requested,
            "operator_interventions": list(self.operator_interventions),
            "intervention_count": len(self.operator_interventions),
            "measurements": dict(self.measurements),
            "failure_taxonomy": list(self.failure_taxonomy),
            "stages": [dict(item) for item in self.stages],
        }


def _reject_json_constant(value: str) -> None:
    raise ReproBenchContractError(f"non-finite JSON number is not allowed: {value}")


def _regular_task_file(path: Path) -> None:
    if path.is_symlink():
        raise ReproBenchContractError("benchmark task must not be a symlink")
    try:
        stat = path.stat()
    except OSError as exc:
        raise ReproBenchContractError(f"could not read benchmark task: {exc}") from exc
    if not path.is_file():
        raise ReproBenchContractError("benchmark task must be a regular JSON file")
    if stat.st_size > _MAX_TASK_BYTES:
        raise ReproBenchContractError(
            f"benchmark task exceeds the {_MAX_TASK_BYTES}-byte host limit"
        )


def _clean_text(value: object, field: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise ReproBenchContractError(f"{field} must be a string")
    text = value.strip()
    if not text:
        raise ReproBenchContractError(f"{field} must not be empty")
    if len(text) > max_length:
        raise ReproBenchContractError(f"{field} exceeds {max_length} characters")
    if "\x00" in text:
        raise ReproBenchContractError(f"{field} contains a NUL byte")
    return text


def _validate_benchmark_paper_source(value: str) -> str:
    """Reject benchmark-controlled local filesystem references and secret-bearing URLs."""
    if _ARXIV_SOURCE.fullmatch(value) or _DOI_SOURCE.fullmatch(value):
        return value
    parsed = urlparse(value)
    if (
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    ):
        return value
    raise ReproBenchContractError(
        "benchmark paper must be an arXiv/DOI identifier or credential-free HTTPS URL "
        "without query/fragment data; local paths, file URLs, and insecure HTTP are not allowed"
    )


def _strip_dot_prefix(value: str) -> str:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _normalize_expected_artifact(value: str, *, field: str) -> str:
    normalized = _strip_dot_prefix(value)
    parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or normalized.endswith("/")
        or _WINDOWS_DRIVE.match(normalized)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ReproBenchContractError(f"{field} must be a relative artifact file name/path")
    return normalized


def _extra_fields(payload: dict[str, Any]) -> tuple[str, ...]:
    extras = [str(key) for key in payload if key not in _CORE_TASK_FIELDS]
    if len(extras) > _MAX_EXTRA_FIELDS:
        raise ReproBenchContractError(
            f"benchmark task may contain at most {_MAX_EXTRA_FIELDS} unknown fields"
        )
    for key in extras:
        if (
            not key
            or len(key) > _MAX_EXTRA_FIELD_NAME
            or key != key.strip()
            or any(ord(character) < 32 for character in key)
        ):
            raise ReproBenchContractError(
                "benchmark task unknown field names must be bounded printable strings"
            )
    return tuple(sorted(extras))


def parse_reprobench_task(payload: dict[str, Any]) -> ReproBenchTask:
    if not isinstance(payload, dict):
        raise ReproBenchContractError("benchmark task JSON must contain an object")
    schema_version = payload.get("schema_version", REPROBENCH_TASK_SCHEMA_VERSION)
    if schema_version != REPROBENCH_TASK_SCHEMA_VERSION:
        raise ReproBenchContractError(
            f"unsupported ReproBench task schema_version: {schema_version!r}"
        )

    task_id = _clean_text(payload.get("task_id"), "task_id", max_length=200)
    if not _TASK_ID.fullmatch(task_id):
        raise ReproBenchContractError(
            "task_id must start with an alphanumeric character and contain only "
            "letters, digits, '.', '_', ':', or '-'"
        )
    domain = _clean_text(payload.get("domain"), "domain", max_length=200)
    paper = _validate_benchmark_paper_source(
        _clean_text(payload.get("paper"), "paper", max_length=4096)
    )

    raw_artifacts = payload.get("expected_artifacts")
    if not isinstance(raw_artifacts, list):
        raise ReproBenchContractError("expected_artifacts must be a list of strings")
    if len(raw_artifacts) > 128:
        raise ReproBenchContractError("expected_artifacts may contain at most 128 entries")
    artifacts: list[str] = []
    for index, raw in enumerate(raw_artifacts):
        artifact = _clean_text(raw, f"expected_artifacts[{index}]", max_length=512)
        artifacts.append(
            _normalize_expected_artifact(artifact, field=f"expected_artifacts[{index}]")
        )
    if len(set(artifacts)) != len(artifacts):
        raise ReproBenchContractError("expected_artifacts must not contain duplicates")

    return ReproBenchTask(
        schema_version=REPROBENCH_TASK_SCHEMA_VERSION,
        task_id=task_id,
        domain=domain,
        paper=paper,
        expected_artifacts=tuple(artifacts),
        extra_fields=_extra_fields(payload),
    )


def load_reprobench_task(path: Path) -> ReproBenchTask:
    _regular_task_file(path)
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReproBenchContractError(f"invalid benchmark task JSON: {exc}") from exc
    return parse_reprobench_task(payload)


def _stage(report: ReproductionReport, name: str) -> str | None:
    for item in report.stages:
        if item.name == name:
            return item.status
    return None


def _artifact_matches(expected: str, actual: str) -> bool:
    expected_norm = _strip_dot_prefix(expected)
    actual_norm = _strip_dot_prefix(actual)
    if "/" in expected_norm:
        return actual_norm == expected_norm
    return Path(actual_norm).name == expected_norm


def _expected_artifact_measurement(
    expected: tuple[str, ...], report: ReproductionReport
) -> tuple[list[str], list[str]]:
    actual = [item.path for item in report.output_artifacts]
    found = [
        item for item in expected if any(_artifact_matches(item, candidate) for candidate in actual)
    ]
    missing = [item for item in expected if item not in found]
    return found, missing


def _failure_taxonomy(report: ReproductionReport, missing_expected: list[str]) -> tuple[str, ...]:
    failures: list[str] = []
    stage_categories = {
        "Paper resolved": "source_resolution_failure",
        "Repository found": "repository_discovery_failure",
        "Repository inspected": "repository_inspection_failure",
        "Datasets downloaded": "dataset_materialization_failure",
        "Environment built": "environment_build_failure",
        "Experiment executed": "experiment_execution_failure",
        "Outputs indexed": "output_indexing_failure",
        "Artifact verification safety": "artifact_verification_failure",
    }
    for stage_name, category in stage_categories.items():
        if _stage(report, stage_name) == "failed":
            failures.append(category)
    if any(not item.passed for item in report.comparisons):
        failures.append("grounded_metric_mismatch")
    if any(not item.passed for item in report.artifact_comparisons):
        failures.append("artifact_comparison_mismatch")
    if missing_expected:
        failures.append("expected_artifact_missing")
    if report.status == "PARTIAL" and not failures:
        failures.append("insufficient_evidence_or_execution")
    elif report.status == "FAIL" and not failures:
        failures.append("unclassified_verirepro_failure")
    return tuple(dict.fromkeys(failures))


def _environment_provenance(report: ReproductionReport) -> dict[str, Any]:
    plan = report.environment_plan if isinstance(report.environment_plan, dict) else {}
    return {
        "repository_commit": plan.get("commit_sha"),
        "environment_fingerprint": plan.get("environment_fingerprint"),
        "environment_reproducibility_grade": plan.get("reproducibility_grade"),
        "dependency_strategy": plan.get("dependency_strategy"),
    }


def build_reprobench_result(
    task: ReproBenchTask,
    report: ReproductionReport,
    *,
    wall_clock_seconds: float,
    execution_requested: bool,
    operator_interventions: tuple[str, ...] = (),
    model_usage: tuple[dict[str, Any], ...] = (),
) -> ReproBenchResult:
    expected_found, expected_missing = _expected_artifact_measurement(task.expected_artifacts, report)
    metric_passed = sum(item.passed for item in report.comparisons)
    artifact_passed = sum(item.passed for item in report.artifact_comparisons)
    experiment_status = _stage(report, "Experiment executed")
    environment_build_status = _stage(report, "Environment built")
    failures = _failure_taxonomy(report, expected_missing)
    model_cost_usd, token_usage = aggregate_model_usage(model_usage)
    hard_failure = any(item != "insufficient_evidence_or_execution" for item in failures)

    if report.status == "FAIL" or expected_missing or hard_failure:
        outcome = "failure"
    elif report.status == "PASS":
        outcome = "success"
    else:
        outcome = "partial"

    measurements: dict[str, Any] = {
        "verirepro_status": report.status,
        "repository": report.repository,
        "environment_plan_success": report.environment_plan is not None,
        **_environment_provenance(report),
        "environment_build_status": environment_build_status,
        "experiment_execution_status": experiment_status,
        "experiment_execution_success": (
            True if experiment_status == "passed" else False if experiment_status == "failed" else None
        ),
        "grounded_metric_comparisons": len(report.comparisons),
        "grounded_metric_passed": metric_passed,
        "grounded_metric_pass_rate": (
            metric_passed / len(report.comparisons) if report.comparisons else None
        ),
        "artifact_comparisons": len(report.artifact_comparisons),
        "artifact_comparisons_passed": artifact_passed,
        "artifact_comparison_pass_rate": (
            artifact_passed / len(report.artifact_comparisons)
            if report.artifact_comparisons
            else None
        ),
        "output_artifact_count": len(report.output_artifacts),
        "expected_artifacts": list(task.expected_artifacts),
        "expected_artifacts_found": expected_found,
        "expected_artifacts_missing": expected_missing,
        "expected_artifact_rate": (
            len(expected_found) / len(task.expected_artifacts)
            if task.expected_artifacts
            else 1.0
        ),
        "model_cost_usd": model_cost_usd,
        "token_usage": token_usage,
    }
    stages = tuple({"name": item.name, "status": item.status} for item in report.stages)
    return ReproBenchResult(
        schema_version=REPROBENCH_RESULT_SCHEMA_VERSION,
        benchmark="reprobench",
        task=task,
        agent={
            "name": "VeriRepro",
            "version": __version__,
            "report_schema_version": REPORT_SCHEMA_VERSION,
        },
        outcome=outcome,
        wall_clock_seconds=round(max(0.0, float(wall_clock_seconds)), 6),
        execution_requested=execution_requested,
        operator_interventions=operator_interventions,
        measurements=measurements,
        failure_taxonomy=failures,
        stages=stages,
    )


def write_reprobench_result(result: ReproBenchResult, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result.to_dict(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return destination


def run_reprobench_task(
    task: ReproBenchTask,
    *,
    workspace_root: Path,
    execute: bool = True,
    repository_url: str | None = None,
    repository_ref: str | None = None,
    command: str | None = None,
    python_version: str = "auto",
    timeout: int = 1800,
    use_llm: bool = True,
    llm_model: str | None = None,
    allow_network: bool = False,
    trust_repository_contract: bool | None = None,
) -> ReproBenchResult:
    interventions: list[str] = []
    if repository_url:
        interventions.append("repository_override")
    if repository_ref:
        interventions.append("repository_ref_override")
    if command:
        interventions.append("command_override")
    if allow_network:
        interventions.append("network_authorization")
    if trust_repository_contract:
        interventions.append("scientific_contract_authorization")

    started = time.monotonic()
    with capture_model_usage() as captured_usage:
        report = reproduce(
            task.paper,
            workspace_root=workspace_root,
            repository_url=repository_url,
            repository_ref=repository_ref,
            command=command,
            execute=execute,
            python_version=python_version,
            timeout=timeout,
            use_llm=use_llm,
            llm_model=llm_model,
            allow_network=allow_network,
            trust_repository_contract=trust_repository_contract,
        )
    elapsed = time.monotonic() - started
    return build_reprobench_result(
        task,
        report,
        wall_clock_seconds=elapsed,
        execution_requested=execute,
        operator_interventions=tuple(interventions),
        model_usage=tuple(captured_usage),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verirepro-reprobench",
        description=(
            "Run a ReproBench v1 task through VeriRepro using a JSON/process boundary. "
            "No ReproBench sibling source code is imported."
        ),
    )
    parser.add_argument("task", type=Path, help="ReproBench task JSON")
    parser.add_argument("--output", type=Path, default=Path("reprobench-result.json"))
    parser.add_argument("--workspace", type=Path, default=Path(".verirepro/benchmark-runs"))
    parser.add_argument("--repo", help="operator repository override (counted as an intervention)")
    parser.add_argument("--ref", dest="repository_ref", help="operator repository ref override")
    parser.add_argument("--command", help="operator experiment command override")
    parser.add_argument("--python", default="auto", dest="python_version")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--no-execute", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--model", dest="llm_model")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--trust-repository-contract", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    task = load_reprobench_task(args.task)
    result = run_reprobench_task(
        task,
        workspace_root=args.workspace,
        execute=not args.no_execute,
        repository_url=args.repo,
        repository_ref=args.repository_ref,
        command=args.command,
        python_version=args.python_version,
        timeout=args.timeout,
        use_llm=not args.no_llm,
        llm_model=args.llm_model,
        allow_network=args.allow_network,
        trust_repository_contract=True if args.trust_repository_contract else None,
    )
    output = write_reprobench_result(result, args.output)
    print(
        f"ReproBench task {task.task_id}: outcome={result.outcome} "
        f"status={result.measurements['verirepro_status']} "
        f"interventions={len(result.operator_interventions)}"
    )
    print(f"Result: {output}")
    return 0 if result.outcome == "success" else 2 if result.outcome == "partial" else 1


if __name__ == "__main__":
    raise SystemExit(main())
