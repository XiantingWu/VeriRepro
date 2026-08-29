from __future__ import annotations

from pathlib import Path
from typing import Any

from reproagent.release_provenance import TRUSTED_CERTIFICATION_WORKFLOWS

from .common import (
    GIT_SHA,
    PINNED_ARXIV_SOURCE,
    SHA256,
    SOFT_PARTIAL_TAXONOMY,
    VALID_REPROBENCH_OUTCOMES,
    contains_sensitive_evidence,
    is_at_least,
    json_object,
    safe_relative_path,
    sha256,
)


def expected_real_paper_cases(evidence_version: str) -> int:
    return 5 if evidence_version.startswith("0.5.") else 15


def front_half_evidence_version(version: str) -> str:
    """The discovery/planning evidence must certify the exact release version."""
    return version


def check_smoke_corpus(root: Path, *, version: str, errors: list[str]) -> None:
    corpus = root / "benchmarks/real-paper-smoke.json"
    if not corpus.is_file():
        return
    payload = json_object(corpus, label="real-paper smoke corpus", errors=errors)
    if payload is None:
        return
    if payload.get("schema_version") != 1:
        errors.append("real-paper smoke corpus must declare schema_version 1")
    if not is_at_least(version, (0, 6, 0)):
        return
    cases = payload.get("cases") or []
    if len(cases) != 15:
        errors.append("0.6+ real-paper smoke corpus must contain exactly 15 release cases")
    if any(
        not isinstance(item, dict)
        or not PINNED_ARXIV_SOURCE.fullmatch(str(item.get("source") or ""))
        for item in cases
    ):
        errors.append("every 0.6+ corpus source must pin an explicit arXiv vN revision")


def check_release_evidence(root: Path, *, version: str, errors: list[str]) -> None:
    evidence_version = front_half_evidence_version(version)
    _check_real_paper_evidence(root, evidence_version=evidence_version, errors=errors)
    _check_environment_planning_evidence(
        root,
        evidence_version=evidence_version,
        errors=errors,
    )
    _check_reprobench_release_evidence(root, version=version, errors=errors)


def _check_real_paper_evidence(
    root: Path,
    *,
    evidence_version: str,
    errors: list[str],
) -> None:
    expected_cases = expected_real_paper_cases(evidence_version)
    relative = f"benchmarks/real-paper-smoke-results-{evidence_version}.json"
    path = root / relative
    if not path.is_file():
        errors.append(f"missing required public-release file: {relative}")
        return

    evidence = json_object(path, label="real-paper release evidence", errors=errors)
    if evidence is None:
        return

    summary = evidence.get("summary") or {}
    results = evidence.get("results") or []
    if evidence.get("schema_version") != 1:
        errors.append("real-paper release evidence must declare schema_version 1")
    if evidence.get("release") != evidence_version:
        errors.append("real-paper release evidence version must match its evidence baseline")
    if summary.get("cases") != expected_cases:
        errors.append(
            f"real-paper release evidence must contain all {expected_cases} release cases"
        )
    if (
        summary.get("expected_repository_found") != expected_cases
        or summary.get("found_rate") != 1.0
    ):
        errors.append(
            f"real-paper release evidence must show {expected_cases}/{expected_cases} expected repositories found"
        )
    if summary.get("top1") != expected_cases or summary.get("top1_rate") != 1.0:
        errors.append(
            f"real-paper release evidence must show {expected_cases}/{expected_cases} expected repositories ranked top-1"
        )
    if len(results) != expected_cases or any(
        not isinstance(item, dict) or item.get("found") is not True or item.get("rank") != 1
        for item in results
    ):
        errors.append("every real-paper release evidence case must be found at rank 1")

    if not evidence_version.startswith("0.5."):
        if summary.get("source_evaluable") != expected_cases:
            errors.append("0.6+ front-half evidence must show every pinned source was evaluable")
        if summary.get("evidence_anchored") != expected_cases:
            errors.append(
                "0.6+ front-half evidence must anchor every expected repository to paper evidence"
            )
        for key in (
            "algorithm_found_rate",
            "algorithm_top1_rate",
            "algorithm_evidence_anchor_rate",
        ):
            if summary.get(key) != 1.0:
                errors.append(f"0.6+ front-half evidence must report {key}=1.0")
        if any(
            not isinstance(item, dict)
            or item.get("discovery_status") != "ok"
            or item.get("evidence_anchored") is not True
            or not PINNED_ARXIV_SOURCE.fullmatch(str(item.get("source") or ""))
            for item in results
        ):
            errors.append(
                "every 0.6+ front-half evidence case must use a pinned arXiv revision and verified discovery evidence"
            )

        corpus = root / "benchmarks/real-paper-smoke.json"
        if corpus.is_file() and evidence.get("corpus_sha256") != sha256(corpus):
            errors.append(
                "front-half evidence corpus SHA-256 must match the committed corpus exactly"
            )
        if evidence.get("corpus_revision_policy") != "explicit-arxiv-vN":
            errors.append(
                "0.6+ front-half evidence must declare the explicit-arxiv-vN revision policy"
            )

    provenance = evidence.get("provenance") or {}
    if not provenance.get("github_actions_run_id") or not provenance.get("head_sha"):
        errors.append("real-paper release evidence must include GitHub Actions run/head provenance")


def _check_environment_planning_evidence(
    root: Path,
    *,
    evidence_version: str,
    errors: list[str],
) -> None:
    if evidence_version.startswith("0.5."):
        return

    relative = f"benchmarks/environment-planning-results-{evidence_version}.json"
    path = root / relative
    if not path.is_file():
        errors.append(f"missing required public-release file: {relative}")
        return

    evidence = json_object(
        path,
        label="environment-planning release evidence",
        errors=errors,
    )
    if evidence is None:
        return

    summary = evidence.get("summary") or {}
    results = evidence.get("results") or []
    if evidence.get("schema_version") != 1:
        errors.append("environment-planning evidence must declare schema_version 1")
    if evidence.get("release") != evidence_version:
        errors.append("environment-planning evidence version must match its evidence baseline")
    if summary.get("cases") != 3:
        errors.append("environment-planning evidence must contain the bounded 3-case gate")
    statuses = summary.get("repository_inspection_status") or {}
    if statuses.get("planned") != 3:
        errors.append("environment-planning evidence must show 3/3 repositories planned")
    if len(results) != 3 or any(
        not isinstance(item, dict)
        or (item.get("repository_inspection") or {}).get("status") != "planned"
        for item in results
    ):
        errors.append("every environment-planning evidence case must have status=planned")

    corpus = root / "benchmarks/real-paper-smoke.json"
    if corpus.is_file() and evidence.get("corpus_sha256") != sha256(corpus):
        errors.append(
            "environment-planning evidence corpus SHA-256 must match the committed corpus"
        )
    provenance = evidence.get("provenance") or {}
    if not provenance.get("github_actions_run_id") or not provenance.get("head_sha"):
        errors.append(
            "environment-planning evidence must include GitHub Actions run/head provenance"
        )


def _check_reprobench_outcome_taxonomy(
    payload: dict[str, Any],
    *,
    task_id: str,
    errors: list[str],
) -> str | None:
    outcome = payload.get("outcome")
    taxonomy = payload.get("failure_taxonomy")
    if outcome not in VALID_REPROBENCH_OUTCOMES:
        errors.append(f"ReproBench result {task_id} has invalid outcome {outcome!r}")
        return None
    if (
        not isinstance(taxonomy, list)
        or not all(isinstance(item, str) and item for item in taxonomy)
        or len(set(taxonomy)) != len(taxonomy)
    ):
        errors.append(
            f"ReproBench result {task_id} failure_taxonomy must be a unique list of non-empty strings"
        )
        return str(outcome)
    if outcome == "success" and taxonomy:
        errors.append(f"ReproBench result {task_id} success must not declare failure taxonomy")
    elif outcome == "partial" and taxonomy != [SOFT_PARTIAL_TAXONOMY]:
        errors.append(
            f"ReproBench result {task_id} partial must declare exactly {SOFT_PARTIAL_TAXONOMY!r}"
        )
    elif outcome == "failure" and (not taxonomy or SOFT_PARTIAL_TAXONOMY in taxonomy):
        errors.append(
            f"ReproBench result {task_id} failure must declare hard failure taxonomy only"
        )
    return str(outcome)


def _check_scientific_references(
    root: Path,
    case: dict[str, Any],
    *,
    task_id: str,
    errors: list[str],
) -> bool:
    references = case.get("scientific_references")
    if references is None or references == []:
        return False
    if not isinstance(references, list):
        errors.append(f"ReproBench case {task_id} scientific_references must be a list")
        return False
    seen: set[str] = set()
    valid = True
    for index, item in enumerate(references):
        if not isinstance(item, dict) or set(item) != {"file", "sha256"}:
            errors.append(
                f"ReproBench case {task_id} scientific reference {index + 1} must contain file+sha256"
            )
            valid = False
            continue
        try:
            rel = safe_relative_path(item.get("file"), field=f"{task_id}.scientific_reference.file")
        except ValueError as exc:
            errors.append(str(exc))
            valid = False
            continue
        relative = rel.as_posix()
        if not relative.startswith("benchmarks/reprobench-reference/") or relative in seen:
            errors.append(
                f"ReproBench case {task_id} scientific references must be unique files under benchmarks/reprobench-reference/"
            )
            valid = False
            continue
        seen.add(relative)
        path = root / rel
        if not path.is_file():
            errors.append(f"missing ReproBench scientific reference: {relative}")
            valid = False
            continue
        declared = item.get("sha256")
        if not isinstance(declared, str) or not SHA256.fullmatch(declared):
            errors.append(f"ReproBench case {task_id} scientific reference SHA-256 is invalid")
            valid = False
        elif declared != sha256(path):
            errors.append(
                f"ReproBench case {task_id} scientific reference SHA-256 does not match committed bytes"
            )
            valid = False
    return valid


def _check_reprobench_release_evidence(
    root: Path,
    *,
    version: str,
    errors: list[str],
) -> None:
    if not is_at_least(version, (0, 7, 0)):
        return

    relative_dir = Path(f"benchmarks/reprobench-results-{version}")
    evidence_dir = root / relative_dir
    manifest_path = evidence_dir / "manifest.json"
    if not manifest_path.is_file():
        errors.append(
            f"missing required ReproBench release evidence: {relative_dir.as_posix()}/manifest.json"
        )
        return

    manifest = json_object(
        manifest_path,
        label="ReproBench release manifest",
        errors=errors,
    )
    if manifest is None:
        return

    if manifest.get("schema_version") != 1:
        errors.append("ReproBench release manifest must declare schema_version 1")
    if manifest.get("release") != version:
        errors.append("ReproBench release manifest release must match pyproject version")
    if manifest.get("gate_passed") is not True:
        errors.append("ReproBench release manifest must record gate_passed=true")

    suite_rel = manifest.get("suite")
    if suite_rel != "benchmarks/reprobench-seed-suite.json":
        errors.append("ReproBench release manifest must bind the canonical seed suite")
    suite_path = root / "benchmarks/reprobench-seed-suite.json"
    if suite_path.is_file() and manifest.get("suite_sha256") != sha256(suite_path):
        errors.append(
            "ReproBench release evidence suite SHA-256 must match the committed seed suite"
        )

    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("ReproBench release manifest must include provenance")
    else:
        run_id = provenance.get("github_actions_run_id")
        head_sha = str(provenance.get("head_sha") or "")
        if not isinstance(run_id, (str, int)) or not str(run_id).isdigit():
            errors.append("ReproBench provenance must include a GitHub Actions run id")
        if not GIT_SHA.fullmatch(head_sha):
            errors.append("ReproBench provenance head_sha must be a 40-character Git SHA")
        if provenance.get("workflow") not in TRUSTED_CERTIFICATION_WORKFLOWS:
            errors.append(
                "ReproBench provenance workflow is not an approved certification workflow"
            )

    cases = manifest.get("cases")
    if not isinstance(cases, list) or not 2 <= len(cases) <= 10:
        errors.append(
            "ReproBench 0.7+ release evidence must contain a bounded 2-10 case seed suite"
        )
        return

    task_ids: set[str] = set()
    result_digests: dict[str, str] = {}
    result_outcomes = {"success": 0, "partial": 0, "failure": 0}
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"ReproBench release case {index + 1} must be an object")
            continue

        task_id = case.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id in task_ids:
            errors.append(
                f"ReproBench release case {index + 1} must have a unique non-empty task_id"
            )
            continue
        task_ids.add(task_id)

        if case.get("gate_passed") is not True or case.get("gate_failures") != []:
            errors.append(f"ReproBench release case {task_id} did not pass its declared gate")

        scientific_reference_valid = _check_scientific_references(
            root,
            case,
            task_id=task_id,
            errors=errors,
        )

        for field, digest_field, base in (
            ("task_file", "task_sha256", root),
            ("result_file", "result_sha256", evidence_dir),
        ):
            try:
                rel = safe_relative_path(case.get(field), field=f"{task_id}.{field}")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            path = base / rel
            try:
                path.resolve().relative_to(base.resolve())
            except ValueError:
                errors.append(f"{task_id}.{field} escapes its evidence root")
                continue
            if not path.is_file():
                errors.append(f"missing ReproBench evidence file: {path.relative_to(root)}")
                continue
            digest = sha256(path)
            declared_digest = case.get(digest_field)
            if not isinstance(declared_digest, str) or not SHA256.fullmatch(declared_digest):
                errors.append(f"{task_id}.{digest_field} must be a SHA-256 digest")
            elif declared_digest != digest:
                errors.append(f"{task_id}.{digest_field} does not match committed bytes")
            if field == "result_file":
                result_digests[path.name] = digest
                payload = json_object(
                    path,
                    label=f"ReproBench result {task_id}",
                    errors=errors,
                )
                if payload is not None:
                    _check_reprobench_result(
                        payload,
                        task_id=task_id,
                        version=version,
                        result_outcomes=result_outcomes,
                        errors=errors,
                    )
                    if (
                        is_at_least(version, (0, 8, 0))
                        and payload.get("outcome") == "success"
                        and not scientific_reference_valid
                    ):
                        errors.append(
                            f"ReproBench scientific success {task_id} must bind benchmark-owned reference evidence"
                        )

    if is_at_least(version, (0, 8, 0)) and result_outcomes["success"] < 1:
        errors.append(
            "ReproBench 0.8+ release evidence must include at least one grounded scientific success"
        )

    _check_reprobench_summary(
        manifest,
        evidence_dir=evidence_dir,
        task_ids=task_ids,
        result_digests=result_digests,
        result_outcomes=result_outcomes,
        errors=errors,
    )


def _check_reprobench_result(
    payload: dict[str, Any],
    *,
    task_id: str,
    version: str,
    result_outcomes: dict[str, int],
    errors: list[str],
) -> None:
    task = payload.get("task") or {}
    agent = payload.get("agent") or {}
    measurements = payload.get("measurements") or {}
    if payload.get("schema_version") != 1 or payload.get("benchmark") != "reprobench":
        errors.append(f"ReproBench result {task_id} has an unsupported schema")
    if task.get("task_id") != task_id:
        errors.append(f"ReproBench result {task_id} task_id mismatch")
    if agent.get("name") != "VeriRepro" or agent.get("version") != version:
        errors.append(f"ReproBench result {task_id} must identify VeriRepro {version}")
    outcome = _check_reprobench_outcome_taxonomy(payload, task_id=task_id, errors=errors)
    if outcome in result_outcomes:
        result_outcomes[outcome] += 1
    if not isinstance(measurements, dict):
        errors.append(f"ReproBench result {task_id} measurements must be an object")
    else:
        for telemetry_key in ("model_cost_usd", "token_usage"):
            if telemetry_key not in measurements:
                errors.append(f"ReproBench result {task_id} must expose {telemetry_key}")
    if contains_sensitive_evidence(payload):
        errors.append(
            f"ReproBench result {task_id} contains a forbidden host/secret-bearing field or path"
        )


def _check_reprobench_summary(
    manifest: dict[str, Any],
    *,
    evidence_dir: Path,
    task_ids: set[str],
    result_digests: dict[str, str],
    result_outcomes: dict[str, int],
    errors: list[str],
) -> None:
    summary_rel = manifest.get("summary_file")
    try:
        summary_path_rel = safe_relative_path(
            summary_rel,
            field="ReproBench manifest summary_file",
        )
    except ValueError as exc:
        errors.append(str(exc))
        return
    summary_path = evidence_dir / summary_path_rel
    if not summary_path.is_file():
        errors.append("ReproBench release summary file is missing")
        return

    summary_digest = sha256(summary_path)
    if manifest.get("summary_sha256") != summary_digest:
        errors.append("ReproBench release summary SHA-256 does not match committed bytes")
    summary_payload = json_object(
        summary_path,
        label="ReproBench release summary",
        errors=errors,
    )
    if summary_payload is None:
        return
    if (
        summary_payload.get("schema_version") != 1
        or summary_payload.get("benchmark") != "reprobench"
    ):
        errors.append("ReproBench release summary has an unsupported schema")
    summary = summary_payload.get("summary") or {}
    if summary.get("cases") != len(task_ids):
        errors.append("ReproBench release summary case count must match the manifest")
    expected_outcomes = {key: value for key, value in result_outcomes.items() if value > 0}
    if summary.get("outcomes") != expected_outcomes:
        errors.append("ReproBench release summary outcomes must match committed result evidence")
    case_count = len(task_ids)
    if case_count:
        for outcome, rate_key in (
            ("success", "success_rate"),
            ("partial", "partial_rate"),
            ("failure", "failure_rate"),
        ):
            expected_rate = result_outcomes[outcome] / case_count
            if summary.get(rate_key) != expected_rate:
                errors.append(
                    f"ReproBench release summary {rate_key} must match committed result evidence"
                )
    inputs = summary_payload.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != len(task_ids):
        errors.append("ReproBench release summary inputs must cover every manifest case")
        return
    input_ids = {item.get("task_id") for item in inputs if isinstance(item, dict)}
    if input_ids != task_ids:
        errors.append("ReproBench release summary task ids must match the manifest")
    for item in inputs:
        if not isinstance(item, dict):
            continue
        filename = item.get("file")
        digest = item.get("sha256")
        if not isinstance(filename, str) or result_digests.get(filename) != digest:
            errors.append(
                "ReproBench release summary input hashes must match committed result files"
            )
            break
