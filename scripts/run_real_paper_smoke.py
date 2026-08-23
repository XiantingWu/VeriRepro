from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests

from reproagent.discovery import discover_paper_artifacts
from reproagent.environment import plan_environment
from reproagent.repository import RepositorySecurityError, clone_repository, inspect_repository
from reproagent.sources import SourceResolutionError, resolve_paper

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "benchmarks/real-paper-smoke.json"
DEFAULT_OUTPUT = ROOT / ".verirepro/benchmarks/real-paper-smoke-results.json"
_CANONICAL_GITHUB_REPO = re.compile(
    r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$",
    re.IGNORECASE,
)
_PINNED_ARXIV_SOURCE = re.compile(r"^\d{4}\.\d{4,5}v\d+$")


def _normalize_repo(url: str) -> str:
    return url.strip().rstrip("/").removesuffix(".git").lower()


def _validate_corpus(corpus: dict[str, Any]) -> list[dict[str, Any]]:
    if corpus.get("schema_version") != 1:
        raise ValueError("unsupported real-paper smoke corpus schema")
    raw_cases = corpus.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("real-paper smoke corpus must contain at least one case")

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    for index, raw in enumerate(raw_cases, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"corpus case {index} must be an object")
        case_id = str(raw.get("id") or "").strip()
        source = str(raw.get("source") or "").strip()
        expected = str(raw.get("expected_repository") or "").strip()
        if not case_id or not source or not expected:
            raise ValueError(f"corpus case {index} requires id, source, and expected_repository")
        if case_id in seen_ids:
            raise ValueError(f"duplicate corpus id: {case_id}")
        if source in seen_sources:
            raise ValueError(f"duplicate corpus source: {source}")
        if not _PINNED_ARXIV_SOURCE.fullmatch(source):
            raise ValueError(
                f"corpus source must pin an explicit arXiv revision like 2103.00020v1: {source}"
            )
        if not _CANONICAL_GITHUB_REPO.fullmatch(expected):
            raise ValueError(
                f"corpus expected_repository must be canonical GitHub HTTPS URL: {expected}"
            )
        seen_ids.add(case_id)
        seen_sources.add(source)
        cases.append(raw)
    return cases


def _expected_candidate(discovery, expected: str):
    normalized = _normalize_repo(expected)
    for candidate in discovery.repository_candidates:
        if _normalize_repo(candidate.url) == normalized:
            return candidate
    return None


def _inspection_error_kind(exc: Exception) -> str:
    if isinstance(exc, RepositorySecurityError):
        return "unsupported"
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError, ConnectionError)):
        return "infrastructure_error"
    text = str(exc).lower()
    if "git clone failed" in text or "timed out" in text or "could not resolve" in text:
        return "infrastructure_error"
    return "planning_error"


def _source_error_kind(exc: Exception) -> str:
    if isinstance(exc, (SourceResolutionError, requests.RequestException, TimeoutError, ConnectionError)):
        return "source_infrastructure_error"
    text = str(exc).lower()
    if any(
        fragment in text
        for fragment in (
            "arxiv",
            "pdf",
            "could not resolve",
            "timed out",
            "connection",
            "http",
        )
    ):
        return "source_infrastructure_error"
    return "pipeline_error"


def _inspect_repository_case(expected: str, destination: Path) -> dict[str, Any]:
    started = time.monotonic()
    try:
        repo = clone_repository(expected, destination)
        profile = inspect_repository(repo)
        plan = plan_environment(profile)
        return {
            "status": "planned",
            "duration_seconds": round(time.monotonic() - started, 3),
            "commit_sha": plan.commit_sha,
            "python_version": plan.python_version,
            "python_source": plan.python_source,
            "dependency_strategy": plan.dependency_strategy,
            "dependency_files": list(plan.dependency_files),
            "reproducibility_grade": plan.reproducibility_grade,
            "gpu_likely": plan.gpu_likely,
            "deterministic_entrypoint_hint": profile.suggested_command,
            "execution_surface": "hinted" if profile.suggested_command else "abstained",
            "warnings": list(plan.warnings),
        }
    except Exception as exc:
        return {
            "status": _inspection_error_kind(exc),
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
            "execution_surface": "not_attempted",
        }


def evaluate_case(
    case: dict[str, Any],
    workspace: Path,
    *,
    inspect_repositories: bool = False,
) -> dict[str, Any]:
    source = str(case["source"])
    expected = str(case["expected_repository"])
    started = time.monotonic()
    paper = resolve_paper(source, workspace / str(case["id"]) / "paper")
    discovery = discover_paper_artifacts(paper)
    discovery_seconds = round(time.monotonic() - started, 3)
    normalized = [_normalize_repo(url) for url in discovery.github_repositories]
    expected_normalized = _normalize_repo(expected)
    rank = normalized.index(expected_normalized) + 1 if expected_normalized in normalized else None
    expected_candidate = _expected_candidate(discovery, expected)
    evidence = []
    if expected_candidate is not None:
        evidence = [
            {
                "source": anchor.source,
                "page": anchor.page,
                "context": anchor.context,
            }
            for anchor in expected_candidate.evidence
        ]

    result: dict[str, Any] = {
        "id": case["id"],
        "source": source,
        "title": case.get("title"),
        "domain": case.get("domain") or "unspecified",
        "expected_repository": expected,
        "discovery_status": "ok",
        "found": rank is not None,
        "rank": rank,
        "evidence_anchored": bool(evidence),
        "expected_repository_evidence": evidence,
        "discovery_seconds": discovery_seconds,
        "top_candidate": discovery.github_repositories[0] if discovery.github_repositories else None,
        "candidate_count": len(discovery.github_repositories),
        "candidates": [
            {
                "url": candidate.url,
                "score": candidate.score,
                "occurrences": candidate.occurrences,
                "reasons": list(candidate.reasons),
                "evidence_count": len(candidate.evidence),
            }
            for candidate in discovery.repository_candidates
        ],
    }
    if inspect_repositories and rank is not None:
        result["repository_inspection"] = _inspect_repository_case(
            expected,
            workspace / str(case["id"]) / "repository",
        )
    elif inspect_repositories:
        result["repository_inspection"] = {
            "status": "not_attempted",
            "reason": "expected repository was not discovered",
            "execution_surface": "not_attempted",
        }
    return result


def _domain_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in results:
        grouped[str(item.get("domain") or "unspecified")].append(item)
    summary: dict[str, Any] = {}
    for domain, items in sorted(grouped.items()):
        evaluable = [item for item in items if item.get("discovery_status", "ok") == "ok"]
        summary[domain] = {
            "cases": len(items),
            "evaluable": len(evaluable),
            "found": sum(bool(item.get("found")) for item in evaluable),
            "top1": sum(item.get("rank") == 1 for item in evaluable),
            "evidence_anchored": sum(bool(item.get("evidence_anchored")) for item in evaluable),
        }
    return summary


def run_corpus(
    corpus_path: Path,
    output_path: Path,
    *,
    inspect_repositories: bool = False,
    max_cases: int | None = None,
) -> dict[str, Any]:
    corpus_bytes = corpus_path.read_bytes()
    corpus_sha256 = hashlib.sha256(corpus_bytes).hexdigest()
    corpus = json.loads(corpus_bytes.decode("utf-8"))
    cases = _validate_corpus(corpus)
    if max_cases is not None:
        if max_cases <= 0:
            raise ValueError("max_cases must be positive")
        cases = cases[:max_cases]

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="verirepro-real-paper-") as temporary:
        workspace = Path(temporary)
        for case in cases:
            try:
                if inspect_repositories:
                    result = evaluate_case(case, workspace, inspect_repositories=True)
                else:
                    result = evaluate_case(case, workspace)
                if "discovery_status" not in result:
                    result["discovery_status"] = "ok"
                if "domain" not in result:
                    result["domain"] = case.get("domain") or "unspecified"
                results.append(result)
            except Exception as exc:
                results.append(
                    {
                        "id": case.get("id"),
                        "source": case.get("source"),
                        "title": case.get("title"),
                        "domain": case.get("domain") or "unspecified",
                        "expected_repository": case.get("expected_repository"),
                        "discovery_status": _source_error_kind(exc),
                        "found": False,
                        "rank": None,
                        "evidence_anchored": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    count = len(results)
    found = sum(bool(item.get("found")) for item in results)
    top1 = sum(item.get("rank") == 1 for item in results)
    anchored = sum(bool(item.get("evidence_anchored")) for item in results)
    evaluable = [item for item in results if item.get("discovery_status", "ok") == "ok"]
    evaluable_count = len(evaluable)
    evaluable_found = sum(bool(item.get("found")) for item in evaluable)
    evaluable_top1 = sum(item.get("rank") == 1 for item in evaluable)
    evaluable_anchored = sum(bool(item.get("evidence_anchored")) for item in evaluable)
    discovery_status = Counter(str(item.get("discovery_status") or "unknown") for item in results)
    inspection_status = Counter(
        str((item.get("repository_inspection") or {}).get("status"))
        for item in results
        if item.get("repository_inspection")
    )
    execution_surface = Counter(
        str((item.get("repository_inspection") or {}).get("execution_surface"))
        for item in results
        if item.get("repository_inspection")
    )
    discovery_times = [float(item["discovery_seconds"]) for item in evaluable if "discovery_seconds" in item]
    payload = {
        "schema_version": 1,
        "corpus": str(corpus_path),
        "corpus_sha256": corpus_sha256,
        "corpus_revision_policy": "explicit-arxiv-vN",
        "mode": {
            "repository_inspection": inspect_repositories,
            "max_cases": max_cases,
        },
        "summary": {
            "cases": count,
            "expected_repository_found": found,
            "top1": top1,
            "evidence_anchored": anchored,
            "found_rate": found / count if count else 0.0,
            "top1_rate": top1 / count if count else 0.0,
            "evidence_anchor_rate": anchored / count if count else 0.0,
            "source_evaluable": evaluable_count,
            "algorithm_found_rate": evaluable_found / evaluable_count if evaluable_count else None,
            "algorithm_top1_rate": evaluable_top1 / evaluable_count if evaluable_count else None,
            "algorithm_evidence_anchor_rate": (
                evaluable_anchored / evaluable_count if evaluable_count else None
            ),
            "mean_discovery_seconds": sum(discovery_times) / len(discovery_times) if discovery_times else 0.0,
            "discovery_status": dict(sorted(discovery_status.items())),
            "domains": _domain_summary(results),
            "repository_inspection_status": dict(sorted(inspection_status.items())),
            "execution_surface": dict(sorted(execution_surface.items())),
        },
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic real-paper repository discovery and optional environment-planning smoke tests."
        )
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--require-top1",
        action="store_true",
        help="fail unless every expected author-declared repository is ranked first",
    )
    parser.add_argument(
        "--require-evidence",
        action="store_true",
        help="fail unless every expected repository has a page-text or PDF-annotation evidence anchor",
    )
    parser.add_argument(
        "--inspect-repositories",
        action="store_true",
        help="shallow-clone discovered expected repositories and measure deterministic environment planning",
    )
    parser.add_argument(
        "--require-environment-plan",
        action="store_true",
        help="with --inspect-repositories, fail unless every case produces an environment plan",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="run only the first N corpus cases (useful for bounded networked planning smoke tests)",
    )
    args = parser.parse_args()
    if args.require_environment_plan and not args.inspect_repositories:
        parser.error("--require-environment-plan requires --inspect-repositories")

    payload = run_corpus(
        args.corpus,
        args.output,
        inspect_repositories=args.inspect_repositories,
        max_cases=args.max_cases,
    )
    summary = payload["summary"]
    print(
        f"Real-paper discovery: found={summary['expected_repository_found']}/{summary['cases']} "
        f"top1={summary['top1']}/{summary['cases']} "
        f"evidence={summary['evidence_anchored']}/{summary['cases']} "
        f"source_evaluable={summary['source_evaluable']}/{summary['cases']}"
    )
    print(f"Corpus SHA-256: {payload['corpus_sha256']}")
    print(f"Discovery status: {summary['discovery_status']}")
    if args.inspect_repositories:
        print(f"Environment planning: {summary['repository_inspection_status']}")
        print(f"Execution surface: {summary['execution_surface']}")
    print(f"Results: {args.output}")

    if summary["expected_repository_found"] != summary["cases"]:
        return 1
    if args.require_top1 and summary["top1"] != summary["cases"]:
        return 1
    if args.require_evidence and summary["evidence_anchored"] != summary["cases"]:
        return 1
    if args.require_environment_plan:
        planned = summary["repository_inspection_status"].get("planned", 0)
        if planned != summary["cases"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
