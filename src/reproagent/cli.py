from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import cast

from . import __version__
from .core import build_reproduction_plan
from .discovery import discover_paper_artifacts, write_discovery
from .environment import docker_available, plan_environment, write_environment_plan
from .intelligence import analyze_paper, write_intelligence
from .llm import LLMConfig, LLMUnavailableError
from .models import ReproductionReport
from .pipeline import reproduce
from .repository import clone_repository, inspect_repository
from .sources import resolve_paper
from .workspaces import allocate_workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verirepro",
        description="Evidence-grounded, verifiable computational paper reproduction.",
    )
    parser.add_argument("--version", action="version", version=f"VeriRepro {__version__}")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    plan = subparsers.add_parser("plan", help="print the reproduction pipeline")
    plan.add_argument("paper", help="arXiv ID/URL, DOI/URL, PDF URL, or local PDF")

    analyze = subparsers.add_parser(
        "analyze",
        help="extract grounded paper facts and ambiguity audit without cloning/executing code",
    )
    analyze.add_argument("paper", help="arXiv ID/URL, DOI/URL, PDF URL, or local PDF")
    analyze.add_argument("--model", dest="llm_model", help="override the configured model")
    analyze.add_argument(
        "--workspace",
        type=Path,
        default=Path(".verirepro/analysis"),
        help="root directory for analysis artifacts",
    )
    analyze.add_argument("--json", action="store_true", help="print paper intelligence as JSON")

    inspect = subparsers.add_parser(
        "inspect",
        help="inspect a research repository and emit an environment/provenance plan",
    )
    inspect.add_argument("repository", help="Git repository URL")
    inspect.add_argument("--ref", help="commit, tag, or branch to pin before inspection")
    inspect.add_argument("--python", default="auto", dest="python_version")
    inspect.add_argument(
        "--workspace",
        type=Path,
        default=Path(".verirepro/inspect"),
        help="root directory for repository inspection artifacts",
    )
    inspect.add_argument("--json", action="store_true", help="print environment plan as JSON")

    run = subparsers.add_parser("reproduce", help="reproduce a computational paper")
    run.add_argument("paper", help="arXiv ID/URL, DOI/URL, PDF URL, or local PDF")
    run.add_argument("--repo", help="override the GitHub repository discovered in the paper")
    run.add_argument("--ref", dest="repository_ref", help="pin repository commit, tag, or branch")
    run.add_argument("--command", dest="experiment_command", help="override the experiment command")
    run.add_argument(
        "--workspace",
        type=Path,
        default=Path(".verirepro/runs"),
        help="root directory for isolated runs",
    )
    run.add_argument(
        "--python",
        default="auto",
        dest="python_version",
        help="Python minor version or 'auto' (default: infer from repository)",
    )
    run.add_argument("--timeout", type=int, default=1800, help="build/run timeout in seconds")
    run.add_argument(
        "--no-execute", action="store_true", help="resolve and plan without Docker execution"
    )
    run.add_argument(
        "--no-llm", action="store_true", help="disable optional model-assisted paper intelligence"
    )
    run.add_argument("--model", dest="llm_model", help="override the configured model")
    run.add_argument(
        "--output-backend",
        choices=("persistent", "ephemeral"),
        default="persistent",
        help=(
            "persist experiment files to the run workspace (default), or use a bounded "
            "container tmpfs and discard file outputs after execution"
        ),
    )
    run.add_argument(
        "--allow-network",
        action="store_true",
        help=(
            "explicitly authorize experiment-container networking when the repository manifest "
            "also requests network access; otherwise Docker networking remains disabled"
        ),
    )
    run.add_argument(
        "--allow-gpu",
        action="store_true",
        help=(
            "explicitly authorize GPU device access when the repository manifest also requests it; "
            "GPU signals alone never grant device access"
        ),
    )
    run.add_argument(
        "--trust-repository-contract",
        action="store_true",
        help=(
            "after reviewing the repository manifest, authorize its expected metrics and "
            "reference artifacts to participate in PASS/FAIL; this does not grant extra "
            "network, host, or container privileges"
        ),
    )
    run.add_argument("--json", action="store_true", help="print the final report as JSON")

    doctor = subparsers.add_parser(
        "doctor", help="check local Git, Docker, and optional model-endpoint configuration"
    )
    doctor.add_argument("--json", action="store_true", help="print secretless diagnostics as JSON")
    doctor.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero unless required local reproduction prerequisites are ready",
    )
    doctor.add_argument(
        "--require-llm",
        action="store_true",
        help="treat model-endpoint configuration as required for readiness instead of optional",
    )
    return parser


def _print_human(report: ReproductionReport) -> None:
    for stage in report.stages:
        symbol = {"passed": "✓", "failed": "✗", "skipped": "○"}.get(stage.status, "•")
        print(f"{symbol} {stage.name}: {stage.detail}")
    print()
    if report.paper_intelligence:
        task = report.paper_intelligence.get("task")
        ambiguities = report.paper_intelligence.get("ambiguities") or []
        completeness = report.paper_intelligence.get("reproduction_completeness")
        if task:
            print(f"Task: {task}")
        if completeness is not None:
            print(f"Critical-field completeness: {float(completeness):.0%}")
        print(f"Ambiguities: {len(ambiguities)}")
        print()
    if report.environment_plan:
        plan = report.environment_plan
        print(
            "Environment: "
            f"Python {plan.get('python_version')} / {plan.get('dependency_strategy')} / "
            f"{str(plan.get('reproducibility_grade', 'weak')).upper()}"
        )
        print(f"Commit: {plan.get('commit_sha') or 'unknown'}")
        print(f"Fingerprint: {str(plan.get('environment_fingerprint') or '')[:16]}")
        print()
    if report.artifact_comparisons:
        print("Artifacts:")
        for artifact in report.artifact_comparisons:
            verdict = "PASS" if artifact.passed else "FAIL"
            print(
                f"  {artifact.kind.title():<7} {artifact.name}: "
                f"{artifact.score:.3f} / {artifact.threshold:.3f}  {verdict}"
            )
        print()
    if report.comparisons:
        width = max(len(item.name) for item in report.comparisons)
        for comparison in report.comparisons:
            print(f"{comparison.name.title():<{width}}  Paper: {comparison.paper:.4f}")
            print(f"{'':<{width}}  Reproduced: {comparison.reproduced:.4f}")
            print(f"{'':<{width}}  Difference: {comparison.difference:+.4f}")
            print()
    print(f"Reproducibility: {report.status}")
    if report.report_markdown:
        print(f"Report: {report.report_markdown}")


def _analyze(args: argparse.Namespace) -> None:
    workspace = allocate_workspace(args.workspace, args.paper)
    paper = resolve_paper(args.paper, workspace / "paper")
    discovery = discover_paper_artifacts(paper)
    write_discovery(discovery, workspace / "artifact-discovery.json")
    try:
        intelligence = analyze_paper(
            paper,
            discovery.github_repositories,
            model=args.llm_model,
        )
    except LLMUnavailableError as exc:
        raise SystemExit(str(exc)) from None
    if intelligence is None:
        raise SystemExit(
            "Model-assisted analysis is not configured. Set VERIREPRO_LLM_BASE_URL and "
            "VERIREPRO_LLM_MODEL (plus VERIREPRO_LLM_API_KEY when required), "
            "or use --no-llm."
        )
    output = write_intelligence(intelligence, workspace / "paper-intelligence.json")
    if args.json:
        print(json.dumps(intelligence.to_dict(), indent=2))
    else:
        print(f"✓ Paper: {paper.pdf_path}")
        print(f"✓ Grounded claims: {intelligence.grounded_claim_count}")
        print(f"✓ Critical-field completeness: {intelligence.reproduction_completeness:.0%}")
        print(f"✓ Ambiguities: {len(intelligence.ambiguities)}")
        print(f"Output: {output}")


def _inspect(args: argparse.Namespace) -> None:
    workspace = allocate_workspace(args.workspace, args.repository)
    repo = clone_repository(args.repository, workspace / "repository", ref=args.ref)
    profile = inspect_repository(repo)
    plan = plan_environment(profile, requested_python=args.python_version)
    output = write_environment_plan(plan, workspace / "environment-plan.json")
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2))
    else:
        print(f"✓ Repository commit: {plan.commit_sha or 'unknown'}")
        print(f"✓ Python: {plan.python_version} ({plan.python_source})")
        print(f"✓ Dependency strategy: {plan.dependency_strategy}")
        print(f"✓ Reproducibility grade: {plan.reproducibility_grade.upper()}")
        print(f"✓ GPU likely: {plan.gpu_likely}")
        for warning in plan.warnings:
            print(f"! {warning}")
        print(f"Output: {output}")


def _doctor_payload(*, require_llm: bool = False) -> dict[str, object]:
    try:
        config = LLMConfig.from_env()
        config_error = None
    except LLMUnavailableError:
        config = None
        config_error = "LLM configuration rejected"

    git_executable = shutil.which("git")
    docker_executable = shutil.which("docker")
    docker_daemon_available = bool(docker_executable and docker_available())
    failed: list[str] = []
    if not git_executable:
        failed.append("git")
    if not docker_executable:
        failed.append("docker")
    elif not docker_daemon_available:
        failed.append("docker_daemon")
    if require_llm and config is None:
        failed.append("llm")

    return {
        "verirepro": {"version": __version__},
        "git": {"executable": git_executable},
        "docker": {
            "executable": docker_executable,
            "daemon_available": docker_daemon_available,
        },
        "llm": {
            "configured": config is not None,
            "endpoint_configured": bool(config.base_url) if config else False,
            "model": config.model if config else None,
            "config_error": config_error,
        },
        "scientific_contract": {
            "repository_contract_trusted": os.getenv(
                "VERIREPRO_TRUST_REPOSITORY_CONTRACT", ""
            ).strip()
            == "1"
        },
        "readiness": {
            "ready": not failed,
            "require_llm": require_llm,
            "failed": failed,
        },
    }


def _doctor(as_json: bool, *, strict: bool = False, require_llm: bool = False) -> int:
    payload = _doctor_payload(require_llm=require_llm)
    readiness = cast(dict[str, object], payload["readiness"])
    ready = bool(readiness["ready"])
    failed = cast(list[object], readiness["failed"])

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        verirepro = cast(dict[str, object], payload["verirepro"])
        git = cast(dict[str, object], payload["git"])
        docker = cast(dict[str, object], payload["docker"])
        llm_diag = cast(dict[str, object], payload["llm"])
        print(f"VeriRepro: {verirepro['version']}")
        print(f"Git: {git['executable'] or 'not found'}")
        print(f"Docker: {docker['executable'] or 'not found'}")
        print(f"Docker daemon: {docker['daemon_available']}")
        print(f"LLM configured: {llm_diag['configured']}")
        print(f"Model endpoint configured: {llm_diag['endpoint_configured']}")
        print(f"Model: {llm_diag['model'] or 'not set'}")
        print(f"Ready: {ready}")
        if failed:
            print("Missing/failed requirement(s): " + ", ".join(str(item) for item in failed))

    return 2 if strict and not ready else 0


def main() -> None:
    args = build_parser().parse_args()
    if hasattr(args, "paper") and not str(getattr(args, "paper", "")).strip():
        raise SystemExit("verirepro: error: paper reference must be a non-empty identifier")
    if args.subcommand == "plan":
        print(json.dumps(build_reproduction_plan(args.paper).to_dict(), indent=2))
        return
    if args.subcommand == "analyze":
        _analyze(args)
        return
    if args.subcommand == "inspect":
        _inspect(args)
        return
    if args.subcommand == "doctor":
        exit_code = _doctor(args.json, strict=args.strict, require_llm=args.require_llm)
        if exit_code:
            raise SystemExit(exit_code)
        return

    report = reproduce(
        args.paper,
        workspace_root=args.workspace,
        repository_url=args.repo,
        repository_ref=args.repository_ref,
        command=args.experiment_command,
        execute=not args.no_execute,
        python_version=args.python_version,
        timeout=args.timeout,
        use_llm=not args.no_llm,
        llm_model=args.llm_model,
        allow_network=args.allow_network,
        allow_gpu=args.allow_gpu,
        output_backend=args.output_backend,
        trust_repository_contract=True if args.trust_repository_contract else None,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_human(report)


if __name__ == "__main__":
    main()
