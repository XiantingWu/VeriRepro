from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from reproagent.discovery import discover_paper_artifacts
from reproagent.intelligence import analyze_paper
from reproagent.llm import LLMConfig, LLMUnavailableError, OpenAICompatibleClient
from reproagent.repository import clone_repository
from reproagent.repository_intelligence import plan_repository_execution
from reproagent.sources import resolve_paper

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "benchmarks/real-paper-smoke.json"
DEFAULT_OUTPUT = ROOT / ".verirepro/benchmarks/llm-planning-smoke-results.json"
RESULT_SCHEMA_VERSION = 2

_ACCEPTED_STATUSES = {
    "safe_command",
    "abstained_no_entrypoint",
    "abstained_unverified_command",
}


def _normalize_repo(url: str) -> str:
    return url.strip().rstrip("/").removesuffix(".git").lower()


def _terminal_class(status: str) -> str:
    if status == "safe_command":
        return "success"
    if status.startswith("abstained_"):
        return "abstained"
    if status in {"repository_not_found", "discovery_mismatch"}:
        return "quality_failure"
    if status in {"paper_analysis_unavailable", "paper_analysis_error", "repository_planning_error"}:
        return "model_failure"
    if status == "infrastructure_or_pipeline_error":
        return "infrastructure_or_pipeline_failure"
    return "unknown_failure"


def _public_usage(usage: dict[str, Any] | None) -> dict[str, Any] | None:
    if usage is None:
        return None
    allowed = (
        "request_model",
        "response_model",
        "duration_seconds",
        "request_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "cost_usd",
        "error",
    )
    return {key: usage.get(key) for key in allowed if key in usage}


def _usage_totals(results: list[dict[str, Any]]) -> dict[str, Any]:
    usages: list[dict[str, Any]] = []
    for item in results:
        for key in ("paper_analysis_usage", "repository_planning_usage"):
            usage = item.get(key)
            if isinstance(usage, dict):
                usages.append(usage)

    integer_fields = (
        "request_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_tokens",
        "reasoning_tokens",
    )
    totals: dict[str, Any] = {"calls_with_telemetry": len(usages)}
    for field in integer_fields:
        values = [value for usage in usages if isinstance((value := usage.get(field)), int)]
        totals[field] = sum(values) if values else None
    durations = [
        float(value)
        for usage in usages
        if isinstance((value := usage.get("duration_seconds")), (int, float))
    ]
    totals["duration_seconds"] = round(sum(durations), 6) if durations else None
    costs = [
        float(value)
        for usage in usages
        if isinstance((value := usage.get("cost_usd")), (int, float))
    ]
    totals["cost_usd"] = round(sum(costs), 10) if costs else None
    return totals


def _finalize_status(result: dict[str, Any], status: str) -> dict[str, Any]:
    result["status"] = status
    result["terminal_class"] = _terminal_class(status)
    result["accepted_outcome"] = status in _ACCEPTED_STATUSES
    return result


def evaluate_case(
    case: dict[str, Any],
    workspace: Path,
    *,
    config: LLMConfig,
) -> dict[str, Any]:
    source = str(case["source"])
    expected = str(case["expected_repository"])
    case_root = workspace / str(case["id"])
    paper = resolve_paper(source, case_root / "paper")
    discovery = discover_paper_artifacts(paper)
    top_repository = discovery.github_repositories[0] if discovery.github_repositories else None

    result: dict[str, Any] = {
        "id": case["id"],
        "source": source,
        "title": case.get("title"),
        "domain": case.get("domain") or "unspecified",
        "expected_repository": expected,
        "top_repository": top_repository,
        "status": "not_attempted",
        "terminal_class": "unknown_failure",
        "accepted_outcome": False,
        "safe_command": None,
    }
    if top_repository is None:
        return _finalize_status(result, "repository_not_found")
    if _normalize_repo(top_repository) != _normalize_repo(expected):
        return _finalize_status(result, "discovery_mismatch")

    repository = clone_repository(top_repository, case_root / "repository")

    paper_client = OpenAICompatibleClient(config)
    try:
        intelligence = analyze_paper(
            paper,
            discovery.github_repositories,
            client=paper_client,
        )
    except LLMUnavailableError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["paper_analysis_usage"] = _public_usage(paper_client.last_usage)
        return _finalize_status(result, "paper_analysis_error")
    result["paper_analysis_usage"] = _public_usage(paper_client.last_usage)
    if intelligence is None:
        return _finalize_status(result, "paper_analysis_unavailable")
    result["grounded_claim_count"] = intelligence.grounded_claim_count
    result["reproduction_completeness"] = intelligence.reproduction_completeness
    result["ambiguity_count"] = len(intelligence.ambiguities)

    planning_client = OpenAICompatibleClient(config)
    try:
        plan = plan_repository_execution(
            repository,
            intelligence,
            client=planning_client,
        )
    except LLMUnavailableError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["repository_planning_usage"] = _public_usage(planning_client.last_usage)
        return _finalize_status(result, "repository_planning_error")
    result["repository_planning_usage"] = _public_usage(planning_client.last_usage)

    if plan is None:
        return _finalize_status(result, "abstained_no_entrypoint")
    result["plan_verification"] = plan.verification
    result["entrypoint"] = plan.entrypoint
    result["evidence_file"] = plan.evidence_file
    result["safe_command"] = plan.command
    return _finalize_status(
        result,
        "safe_command" if plan.command else "abstained_unverified_command",
    )


def run_corpus(
    corpus_path: Path,
    output_path: Path,
    *,
    config: LLMConfig,
    max_cases: int,
) -> dict[str, Any]:
    if max_cases <= 0:
        raise ValueError("max_cases must be positive")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if corpus.get("schema_version") != 1:
        raise ValueError("unsupported real-paper smoke corpus schema")
    cases = list(corpus.get("cases") or [])[:max_cases]

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="verirepro-llm-planning-") as temporary:
        workspace = Path(temporary)
        for case in cases:
            try:
                results.append(evaluate_case(case, workspace, config=config))
            except Exception as exc:
                result = {
                    "id": case.get("id"),
                    "source": case.get("source"),
                    "title": case.get("title"),
                    "domain": case.get("domain") or "unspecified",
                    "expected_repository": case.get("expected_repository"),
                    "safe_command": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                results.append(_finalize_status(result, "infrastructure_or_pipeline_error"))

    statuses = Counter(str(item.get("status")) for item in results)
    terminal_classes = Counter(str(item.get("terminal_class")) for item in results)
    safe_commands = sum(item.get("status") == "safe_command" for item in results)
    abstentions = sum(item.get("terminal_class") == "abstained" for item in results)
    accepted = sum(bool(item.get("accepted_outcome")) for item in results)
    blocking = len(results) - accepted
    analyzed = sum("grounded_claim_count" in item for item in results)
    payload = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "corpus_schema_version": corpus.get("schema_version"),
        "corpus": str(corpus_path),
        "model": config.model,
        "command_execution": "never",
        "summary": {
            "cases": len(results),
            "paper_analyzed": analyzed,
            "safe_command_planned": safe_commands,
            "abstained": abstentions,
            "accepted_outcomes": accepted,
            "blocking_failures": blocking,
            "statuses": dict(sorted(statuses.items())),
            "terminal_classes": dict(sorted(terminal_classes.items())),
            "usage": _usage_totals(results),
        },
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure evidence-grounded LiteLLM paper analysis and safe repository command planning. "
            "This smoke test never executes generated commands."
        )
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-cases", type=int, default=3)
    parser.add_argument("--model", default=None, help="override the configured LiteLLM model alias")
    parser.add_argument(
        "--allow-blocking-failures",
        action="store_true",
        help="emit measurements without failing the process when a case has a non-abstention failure",
    )
    args = parser.parse_args()

    config = LLMConfig.from_env(model=args.model)
    if config is None:
        parser.error(
            "LiteLLM is not configured; set VERIREPRO_LITELLM_BASE_URL and "
            "VERIREPRO_LITELLM_MODEL (plus VERIREPRO_LITELLM_API_KEY when required)"
        )

    payload = run_corpus(
        args.corpus,
        args.output,
        config=config,
        max_cases=args.max_cases,
    )
    summary = payload["summary"]
    print(
        f"LLM planning smoke: analyzed={summary['paper_analyzed']}/{summary['cases']} "
        f"safe_command={summary['safe_command_planned']} abstained={summary['abstained']} "
        f"blocking={summary['blocking_failures']}"
    )
    print(f"Statuses: {summary['statuses']}")
    print(f"Terminal classes: {summary['terminal_classes']}")
    print(f"Usage: {summary['usage']}")
    print(f"Results: {args.output}")
    if args.allow_blocking_failures:
        return 0
    return 0 if summary["blocking_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())