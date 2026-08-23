from __future__ import annotations

import math
import re
from pathlib import Path

from .artifacts import compare_artifacts, index_outputs, write_artifact_results
from .config import MetricSpec, load_manifest
from .datasets import download_datasets
from .discovery import discover_paper_artifacts, write_discovery
from .environment import (
    DockerUnavailableError,
    build_image,
    generate_dockerfile,
    image_tag,
    plan_environment,
    write_environment_plan,
)
from .experiment import run_in_docker
from .intelligence import analyze_paper, write_intelligence
from .llm import LLMUnavailableError
from .metrics import compare_metrics, extract_output_metrics
from .model_artifacts import materialize_model_artifacts
from .models import ReproductionReport, StageResult
from .reporting import write_report
from .repository import clone_repository, inspect_repository
from .repository_intelligence import plan_repository_execution, write_repository_plan
from .sources import resolve_paper
from .workspaces import allocate_workspace

_AUTO_METRIC_TOLERANCE = 0.01
_AUTO_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "accuracy": ("accuracy", "acc"),
    "f1": ("f1", "f1_score", "f1-score", "f1 score"),
    "auc": ("auc", "auroc", "roc auc", "roc-auc"),
    "precision": ("precision",),
    "recall": ("recall",),
}
_METRIC_CANONICAL = {
    alias.replace("-", "_").replace(" ", "_"): canonical
    for canonical, aliases in _AUTO_METRIC_ALIASES.items()
    for alias in aliases
}


def _discovery_payload(discovery) -> dict[str, object]:
    return {
        "github_repositories": list(discovery.github_repositories),
        "dataset_urls": list(discovery.dataset_urls),
        "repository_candidates": [
            {
                "url": item.url,
                "score": item.score,
                "occurrences": item.occurrences,
                "reasons": list(item.reasons),
                "evidence": [
                    {
                        "source": anchor.source,
                        "page": anchor.page,
                        "context": anchor.context,
                    }
                    for anchor in item.evidence
                ],
            }
            for item in discovery.repository_candidates
        ],
    }


def _canonical_auto_metric(name: str) -> str | None:
    key = re.sub(r"\s+", "_", name.strip().lower().replace("-", "_"))
    return _METRIC_CANONICAL.get(key)


def _quote_supports_metric_name(canonical: str, quote: str) -> bool:
    normalized = quote.lower()
    patterns = {
        "accuracy": r"\b(?:accuracy|acc\.?)(?:\b|\s)",
        "f1": r"\bf1(?:[-_ ]?score)?\b",
        "auc": r"\b(?:auroc|auc|roc[- ]?auc)\b",
        "precision": r"\bprecision\b",
        "recall": r"\brecall\b",
    }
    pattern = patterns.get(canonical)
    return bool(pattern and re.search(pattern, normalized))


def _auto_verdict_metrics(intelligence) -> tuple[dict[str, float], tuple[MetricSpec, ...], tuple[str, ...]]:
    """Return only deterministic, unambiguous paper metrics eligible for automatic verdicts.

    LLM-suggested tolerances are never trusted. Only normalized bounded metrics
    with a metric name supported by the grounded quote are eligible, all using
    VeriRepro's fixed absolute tolerance. Conflicting grounded values for the
    same canonical metric are excluded rather than arbitrarily selecting one.
    """
    grouped: dict[str, list[float]] = {}
    excluded: set[str] = set()
    for item in intelligence.metrics:
        if item.verification not in {"verified", "approximate"}:
            continue
        canonical = _canonical_auto_metric(item.name)
        if canonical is None:
            excluded.add(item.name)
            continue
        if not _quote_supports_metric_name(canonical, item.quote):
            excluded.add(canonical)
            continue
        grouped.setdefault(canonical, []).append(float(item.value))

    paper_metrics: dict[str, float] = {}
    specs: list[MetricSpec] = []
    for canonical, values in grouped.items():
        first = values[0]
        if any(not math.isclose(first, other, rel_tol=1e-9, abs_tol=1e-12) for other in values[1:]):
            excluded.add(canonical)
            continue
        paper_metrics[canonical] = first
        specs.append(
            MetricSpec(
                name=canonical,
                paper=first,
                tolerance=_AUTO_METRIC_TOLERANCE,
            )
        )
    return paper_metrics, tuple(specs), tuple(sorted(excluded))


def _effective_network(manifest_requests_network: bool, user_allows_network: bool) -> bool:
    """A repository may request network access, but only the user can authorize it."""
    return bool(manifest_requests_network and user_allows_network)


def _effective_gpu(manifest_requests_gpu: bool, user_allows_gpu: bool) -> bool:
    """Repository GPU requests never grant device access without explicit host authorization."""
    return bool(manifest_requests_gpu and user_allows_gpu)


def reproduce(
    source: str,
    *,
    workspace_root: Path = Path(".verirepro/runs"),
    repository_url: str | None = None,
    repository_ref: str | None = None,
    command: str | None = None,
    execute: bool = True,
    python_version: str = "auto",
    timeout: int = 1800,
    use_llm: bool = True,
    llm_model: str | None = None,
    allow_network: bool = False,
    allow_gpu: bool = False,
    output_backend: str = "persistent",
    trust_repository_contract: bool | None = None,
) -> ReproductionReport:
    workspace = allocate_workspace(workspace_root, source)
    stages: list[StageResult] = []
    stacks: tuple[str, ...] = ()
    paper_metrics: dict[str, float] = {}
    reproduced_metrics: dict[str, float] = {}
    comparisons = []
    artifact_comparisons = []
    output_artifacts = []
    chosen_repo: str | None = repository_url
    experiment_failed = False
    output_index_failed = False
    intelligence = None
    repository_plan = None
    environment_plan = None
    discovery_payload: dict[str, object] | None = None

    if output_backend not in {"persistent", "ephemeral"}:
        raise ValueError("output_backend must be 'persistent' or 'ephemeral'")

    try:
        paper = resolve_paper(source, workspace / "paper")
        page_count = paper.metadata.get("page_count")
        detail = str(paper.pdf_path)
        if page_count:
            detail += f" ({page_count} page(s))"
        stages.append(StageResult("Paper resolved", "passed", detail))
    except Exception as exc:
        stages.append(StageResult("Paper resolved", "failed", str(exc)))
        return write_report(
            ReproductionReport(
                source=source,
                status="FAIL",
                repository=chosen_repo,
                stacks=(),
                stages=stages,
                paper_metrics={},
                reproduced_metrics={},
                comparisons=[],
                workspace=workspace,
            )
        )

    discovery = discover_paper_artifacts(paper)
    discovery_payload = _discovery_payload(discovery)
    write_discovery(discovery, workspace / "artifact-discovery.json")
    top = discovery.repository_candidates[0] if discovery.repository_candidates else None
    top_detail = (
        f"; top candidate score={top.score} ({', '.join(top.reasons) or 'frequency'})"
        if top else ""
    )
    stages.append(
        StageResult(
            "Artifacts discovered",
            "passed",
            f"found {len(discovery.github_repositories)} GitHub repo(s) and "
            f"{len(discovery.dataset_urls)} dataset URL(s) in {len(paper.text):,} searchable characters"
            f"{top_detail}",
        )
    )

    if use_llm:
        try:
            intelligence = analyze_paper(
                paper,
                discovery.github_repositories,
                model=llm_model,
            )
            if intelligence is None:
                stages.append(
                    StageResult(
                        "Paper intelligence",
                        "skipped",
                        "LiteLLM is not configured; set VERIREPRO_LITELLM_BASE_URL and "
                        "VERIREPRO_LITELLM_MODEL (plus VERIREPRO_LITELLM_API_KEY when required), "
                        "or use the standard LITELLM_* aliases",
                    )
                )
            else:
                write_intelligence(intelligence, workspace / "paper-intelligence.json")
                verified = sum(
                    item.verification in {"verified", "approximate"} for item in intelligence.evidence
                )
                unverified = sum(item.verification == "unverified" for item in intelligence.evidence)
                stages.append(
                    StageResult(
                        "Paper intelligence",
                        "passed",
                        f"model={intelligence.model}; {verified} grounded claim(s), "
                        f"{unverified} unverified claim(s), {len(intelligence.ambiguities)} ambiguity item(s), "
                        f"{intelligence.reproduction_completeness:.0%} critical-field completeness",
                    )
                )
                if not chosen_repo and intelligence.canonical_repository:
                    chosen_repo = intelligence.canonical_repository
        except LLMUnavailableError as exc:
            stages.append(StageResult("Paper intelligence", "skipped", str(exc)))
        except Exception as exc:
            stages.append(StageResult("Paper intelligence", "skipped", f"analysis failed safely: {exc}"))
    else:
        stages.append(StageResult("Paper intelligence", "skipped", "disabled by --no-llm"))

    if not chosen_repo and discovery.github_repositories:
        chosen_repo = discovery.github_repositories[0]
    if not chosen_repo:
        stages.append(
            StageResult(
                "Repository found",
                "failed",
                "no GitHub repository was found in the paper; pass --repo explicitly",
            )
        )
        return write_report(
            ReproductionReport(
                source=source,
                status="FAIL",
                repository=None,
                stacks=(),
                stages=stages,
                paper_metrics={},
                reproduced_metrics={},
                comparisons=[],
                workspace=workspace,
                paper_intelligence=intelligence.to_dict() if intelligence else None,
                artifact_discovery=discovery_payload,
            )
        )

    stages.append(
        StageResult(
            "Repository found",
            "passed",
            chosen_repo + (f" @ {repository_ref}" if repository_ref else ""),
        )
    )
    try:
        repo = clone_repository(chosen_repo, workspace / "repository", ref=repository_ref)
        profile = inspect_repository(repo)
        stacks = profile.stacks
        manifest = load_manifest(
            profile.manifest_path,
            trust_scientific_contract=trust_repository_contract,
        )
        manifest_label = profile.manifest_path.name if profile.manifest_path else "verirepro.yaml"
        commit = profile.commit_sha[:12] if profile.commit_sha else "unknown"
        stages.append(
            StageResult(
                "Repository inspected",
                "passed",
                f"commit={commit}; stack={', '.join(stacks)}; "
                f"dependencies={profile.dependency_files or 'none'}",
            )
        )
    except Exception as exc:
        stages.append(StageResult("Repository inspected", "failed", str(exc)))
        return write_report(
            ReproductionReport(
                source=source,
                status="FAIL",
                repository=chosen_repo,
                stacks=stacks,
                stages=stages,
                paper_metrics={},
                reproduced_metrics={},
                comparisons=[],
                workspace=workspace,
                paper_intelligence=intelligence.to_dict() if intelligence else None,
                artifact_discovery=discovery_payload,
            )
        )

    declared_contract_items = manifest.declared_metric_count + manifest.declared_artifact_count
    if declared_contract_items and manifest.scientific_contract_trusted:
        stages.append(
            StageResult(
                "Scientific contract",
                "passed",
                f"host explicitly trusted {manifest.declared_metric_count} repository-declared metric(s) "
                f"and {manifest.declared_artifact_count} artifact comparison(s) from {manifest_label}",
            )
        )
    elif declared_contract_items:
        stages.append(
            StageResult(
                "Scientific contract",
                "skipped",
                f"ignored {manifest.declared_metric_count} repository-declared metric(s) and "
                f"{manifest.declared_artifact_count} artifact comparison(s) from {manifest_label}; "
                "third-party repositories cannot self-certify PASS. Review the contract and use "
                "--trust-repository-contract only if you intend to authorize those expectations",
            )
        )
    else:
        stages.append(
            StageResult(
                "Scientific contract",
                "skipped",
                "no repository-declared scientific expectations were available; verdict evidence must come "
                "from page/quote-grounded paper intelligence",
            )
        )

    environment_plan = plan_environment(profile, requested_python=python_version)
    write_environment_plan(environment_plan, workspace / "environment-plan.json")
    stages.append(
        StageResult(
            "Environment planned",
            "passed",
            f"Python {environment_plan.python_version} ({environment_plan.python_source}); "
            f"strategy={environment_plan.dependency_strategy}; "
            f"reproducibility={environment_plan.reproducibility_grade}; "
            f"fingerprint={environment_plan.environment_fingerprint[:12]}",
        )
    )
    if environment_plan.warnings:
        stages.append(
            StageResult(
                "Environment diagnostics",
                "passed",
                " | ".join(environment_plan.warnings),
            )
        )

    run_command = command or manifest.command
    command_source = "CLI" if command else manifest_label if manifest.command else None
    if not run_command and use_llm:
        try:
            repository_plan = plan_repository_execution(repo, intelligence, model=llm_model)
            if repository_plan:
                write_repository_plan(repository_plan, workspace / "repository-plan.json")
                if repository_plan.command:
                    run_command = repository_plan.command
                    command_source = "verified repository agent plan"
                    stages.append(
                        StageResult(
                            "Repository execution planned",
                            "passed",
                            f"{repository_plan.command} grounded in {repository_plan.evidence_file}",
                        )
                    )
                else:
                    stages.append(
                        StageResult(
                            "Repository execution planned",
                            "skipped",
                            "the model could not produce a repository-grounded command that passed evidence and command validation",
                        )
                    )
            else:
                stages.append(
                    StageResult(
                        "Repository execution planned",
                        "skipped",
                        "no eligible repository entrypoints or LiteLLM configuration",
                    )
                )
        except LLMUnavailableError as exc:
            stages.append(StageResult("Repository execution planned", "skipped", str(exc)))
        except Exception as exc:
            stages.append(StageResult("Repository execution planned", "skipped", f"planning failed safely: {exc}"))

    if not run_command and profile.suggested_command:
        run_command = profile.suggested_command
        command_source = "conventional entrypoint"

    if run_command and not any(stage.name == "Repository execution planned" for stage in stages):
        stages.append(
            StageResult(
                "Repository execution planned",
                "passed",
                f"using {command_source}: `{run_command}`",
            )
        )
    elif not run_command and not any(stage.name == "Repository execution planned" for stage in stages):
        stages.append(StageResult("Repository execution planned", "skipped", "LLM planning disabled"))

    network_enabled = _effective_network(manifest.network, allow_network)
    if manifest.network and allow_network:
        network_detail = "repository requested network access and the user explicitly authorized --allow-network"
    elif manifest.network:
        network_detail = "repository requested network access, but it was denied because --allow-network was not provided"
    else:
        network_detail = "repository did not request network access; Docker networking remains disabled"
    stages.append(StageResult("Network policy", "passed", network_detail))

    # Older internal manifest/plan-like objects may not carry optional GPU fields.
    # Absence always means CPU-only; compatibility must never grant device access.
    manifest_requests_gpu = bool(getattr(manifest, "gpu", False))
    gpu_likely = bool(getattr(environment_plan, "gpu_likely", False))
    gpu_enabled = _effective_gpu(manifest_requests_gpu, allow_gpu)
    if manifest_requests_gpu and allow_gpu:
        gpu_detail = (
            "repository requested GPU access and the user explicitly authorized --allow-gpu; "
            "Docker will request all configured GPU devices"
        )
    elif manifest_requests_gpu:
        gpu_detail = (
            "repository requested GPU access, but it was denied because --allow-gpu was not provided"
        )
    elif gpu_likely:
        gpu_detail = (
            "CUDA/GPU signals were detected, but the repository manifest did not request GPU access; "
            "Docker remains CPU-only"
        )
    else:
        gpu_detail = "repository did not request GPU access; Docker remains CPU-only"
    stages.append(StageResult("GPU policy", "passed", gpu_detail))

    dockerfile = generate_dockerfile(
        profile,
        workspace / "Dockerfile.verirepro",
        environment_plan.python_version,
    )

    dataset_dir = workspace / "datasets"
    model_dir = workspace / "models"
    # Older internal manifest-like fixtures may not carry optional model artifacts.
    # Absence always means no model files and grants no runtime capability.
    model_artifacts = tuple(getattr(manifest, "model_artifacts", ()))
    if manifest.datasets:
        try:
            dataset_provenance = workspace / "dataset-provenance.json"
            downloaded = download_datasets(
                manifest.datasets,
                dataset_dir,
                provenance_path=dataset_provenance,
            )
            stages.append(
                StageResult(
                    "Datasets downloaded",
                    "passed",
                    f"materialized {len(downloaded)} dataset(s); provenance=dataset-provenance.json",
                )
            )
        except Exception as exc:
            stages.append(StageResult("Datasets downloaded", "failed", str(exc)))
            experiment_failed = True
    else:
        stages.append(
            StageResult(
                "Datasets downloaded",
                "skipped",
                f"no downloadable datasets declared in {manifest_label}",
            )
        )

    if model_artifacts:
        try:
            model_provenance = workspace / "model-artifact-provenance.json"
            materialized_models = materialize_model_artifacts(
                model_artifacts,
                model_dir,
                provenance_path=model_provenance,
            )
            stages.append(
                StageResult(
                    "Model artifacts materialized",
                    "passed",
                    f"verified {len(materialized_models)} checksum-bound model artifact(s); "
                    "mounted read-only at /models during execution",
                )
            )
        except Exception as exc:
            stages.append(StageResult("Model artifacts materialized", "failed", str(exc)))
            experiment_failed = True
    else:
        stages.append(
            StageResult(
                "Model artifacts materialized",
                "skipped",
                f"no checksum-bound model artifacts declared in {manifest_label}",
            )
        )

    metric_specs: tuple[MetricSpec, ...] = manifest.metrics
    if manifest.metrics:
        paper_metrics = {item.name.lower(): item.paper for item in manifest.metrics}
    elif intelligence:
        paper_metrics, metric_specs, excluded_metrics = _auto_verdict_metrics(intelligence)
        if excluded_metrics:
            stages.append(
                StageResult(
                    "Automatic metric policy",
                    "skipped",
                    "excluded from automatic PASS/FAIL: " + ", ".join(excluded_metrics),
                )
            )
        if paper_metrics:
            stages.append(
                StageResult(
                    "Automatic metric policy",
                    "passed",
                    f"eligible grounded metric(s): {', '.join(sorted(paper_metrics))}; "
                    f"fixed absolute tolerance={_AUTO_METRIC_TOLERANCE}",
                )
            )

    output_dir = workspace / "outputs"
    if output_backend == "ephemeral":
        output_policy_detail = (
            "ephemeral bounded tmpfs; experiment file outputs are discarded after the container exits "
            "and never bind-mounted to the host"
        )
    else:
        output_policy_detail = (
            "persistent run-scoped host bind; post-run indexing remains host-budgeted but the bind "
            "is not a hard filesystem quota"
        )
    stages.append(StageResult("Output policy", "passed", output_policy_detail))

    if execute and run_command and not experiment_failed:
        try:
            tag = image_tag(chosen_repo, environment_plan.environment_fingerprint)
            build_image(repo, dockerfile, tag, timeout=timeout)
            stages.append(StageResult("Environment built", "passed", f"Docker image {tag}"))
            result = run_in_docker(
                tag,
                run_command,
                output_dir,
                dataset_dir,
                model_dir if model_artifacts else None,
                output_backend=output_backend,
                network=network_enabled,
                gpu=gpu_enabled,
                timeout=timeout,
            )
            (workspace / "experiment.stdout.log").write_text(result.stdout, encoding="utf-8")
            (workspace / "experiment.stderr.log").write_text(result.stderr, encoding="utf-8")
            if result.succeeded:
                stages.append(
                    StageResult(
                        "Experiment executed",
                        "passed",
                        f"exit=0 in {result.duration_seconds:.1f}s using `{run_command}`",
                    )
                )
            else:
                experiment_failed = True
                stages.append(
                    StageResult(
                        "Experiment executed",
                        "failed",
                        f"exit={result.exit_code}; see experiment.stderr.log",
                    )
                )
            reproduced_metrics = extract_output_metrics(result.stdout + "\n" + result.stderr)
        except DockerUnavailableError as exc:
            experiment_failed = True
            stages.append(StageResult("Environment built", "failed", str(exc)))
            stages.append(
                StageResult(
                    "Experiment executed",
                    "skipped",
                    "environment build failed; experiment was not started",
                )
            )
        except Exception as exc:
            experiment_failed = True
            stages.append(StageResult("Experiment executed", "failed", str(exc)))
    elif execute and run_command and experiment_failed:
        stages.append(
            StageResult(
                "Experiment executed",
                "skipped",
                "a required pre-execution stage failed; experiment was not started",
            )
        )
    elif not execute:
        stages.append(StageResult("Experiment executed", "skipped", "execution disabled by --no-execute"))
    else:
        stages.append(
            StageResult(
                "Experiment executed",
                "skipped",
                "no safe reproduction command found; add verirepro.yaml, use --command, "
                "or enable grounded repository planning",
            )
        )

    try:
        output_artifacts = list(index_outputs(output_dir))
        if output_artifacts:
            counts: dict[str, int] = {}
            for item in output_artifacts:
                counts[item.kind] = counts.get(item.kind, 0) + 1
            summary = ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))
            stages.append(StageResult("Outputs indexed", "passed", f"{len(output_artifacts)} artifact(s): {summary}"))
        else:
            stages.append(StageResult("Outputs indexed", "skipped", "experiment produced no persisted output artifacts"))
    except Exception as exc:
        output_artifacts = []
        output_index_failed = True
        experiment_failed = True
        stages.append(
            StageResult(
                "Outputs indexed",
                "failed",
                f"host-side output indexing failed safely: {exc}",
            )
        )

    if manifest.artifacts and execute and not output_index_failed:
        try:
            artifact_comparisons = list(compare_artifacts(manifest.artifacts, repo, output_dir))
            write_artifact_results(
                tuple(artifact_comparisons),
                tuple(output_artifacts),
                workspace / "artifact-results.json",
            )
            artifact_passed = sum(item.passed for item in artifact_comparisons)
            stages.append(
                StageResult(
                    "Artifacts compared",
                    "passed" if artifact_passed == len(artifact_comparisons) else "failed",
                    f"{artifact_passed}/{len(artifact_comparisons)} host-authorized figure/table/file artifact(s) matched",
                )
            )
        except Exception as exc:
            artifact_comparisons = []
            experiment_failed = True
            stages.append(
                StageResult(
                    "Artifact verification safety",
                    "failed",
                    f"host-side artifact verification failed safely: {exc}",
                )
            )
    elif manifest.artifacts and output_index_failed:
        stages.append(
            StageResult(
                "Artifacts compared",
                "skipped",
                "output indexing failed its host safety budget; artifact comparisons were not attempted",
            )
        )
    elif manifest.artifacts:
        stages.append(
            StageResult(
                "Artifacts compared",
                "skipped",
                "execution disabled; host-authorized artifact comparisons were not run",
            )
        )
    else:
        if output_artifacts:
            write_artifact_results((), tuple(output_artifacts), workspace / "artifact-results.json")
        stages.append(
            StageResult(
                "Artifacts compared",
                "skipped",
                "no host-authorized artifact comparison contract was available",
            )
        )

    comparisons = compare_metrics(paper_metrics, reproduced_metrics, metric_specs)
    if comparisons:
        passed = sum(item.passed for item in comparisons)
        stages.append(
            StageResult(
                "Results compared",
                "passed" if passed == len(comparisons) else "failed",
                f"{passed}/{len(comparisons)} evidence-authorized metric(s) within tolerance",
            )
        )
    else:
        stages.append(
            StageResult(
                "Results compared",
                "skipped",
                "no comparable host-authorized or page/quote-grounded paper/output metrics were available",
            )
        )

    metric_failed = any(not item.passed for item in comparisons)
    artifact_failed = any(not item.passed for item in artifact_comparisons)
    has_verified_result = bool(comparisons or artifact_comparisons)
    if experiment_failed or metric_failed or artifact_failed:
        status = "FAIL"
    elif has_verified_result:
        status = "PASS"
    else:
        status = "PARTIAL"

    return write_report(
        ReproductionReport(
            source=source,
            status=status,
            repository=chosen_repo,
            stacks=stacks,
            stages=stages,
            paper_metrics=paper_metrics,
            reproduced_metrics=reproduced_metrics,
            comparisons=comparisons,
            workspace=workspace,
            paper_intelligence=intelligence.to_dict() if intelligence else None,
            repository_plan=repository_plan.to_dict() if repository_plan else None,
            environment_plan=environment_plan.to_dict(),
            artifact_discovery=discovery_payload,
            artifact_comparisons=artifact_comparisons,
            output_artifacts=output_artifacts,
        )
    )
