from __future__ import annotations

from pathlib import Path

from .config import ArtifactSpec, MetricSpec, load_manifest
from .datasets import download_datasets
from .discovery import discover_paper_artifacts, write_discovery
from .environment import generate_dockerfile, plan_environment, write_environment_plan
from .intelligence import analyze_paper, write_intelligence
from .llm import LLMUnavailableError
from .model_artifacts import materialize_model_artifacts
from .models import DiscoveryResult, ReproductionReport, StageResult
from .pipeline_execution import execute_experiment
from .pipeline_policy import (
    AUTO_METRIC_TOLERANCE,
    gpu_policy_detail,
    network_policy_detail,
    output_policy_detail,
)
from .pipeline_policy import (
    auto_verdict_metrics as _auto_verdict_metrics,
)
from .pipeline_policy import (
    effective_gpu as _effective_gpu,
)
from .pipeline_policy import (
    effective_network as _effective_network,
)
from .pipeline_reporting import write_completed_report, write_failure_report
from .pipeline_verification import verify_results
from .repository import clone_repository, inspect_repository
from .repository_intelligence import plan_repository_execution, write_repository_plan
from .sources import resolve_paper
from .workspaces import allocate_workspace


def _discovery_payload(discovery: DiscoveryResult) -> dict[str, object]:
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
    trusted_artifact_contract: tuple[ArtifactSpec, ...] = (),
    trusted_reference_root: Path | None = None,
) -> ReproductionReport:
    """Orchestrate one evidence-grounded reproduction run.

    Policy, third-party execution, scientific verification, and report persistence
    live in dedicated modules. This function intentionally remains the stage
    coordinator so the public API has one stable entrypoint without a god module.
    """
    workspace = allocate_workspace(workspace_root, source)
    stages: list[StageResult] = []
    stacks: tuple[str, ...] = ()
    paper_metrics: dict[str, float] = {}
    reproduced_metrics: dict[str, float] = {}
    chosen_repo: str | None = repository_url
    preexecution_failed = False
    intelligence = None
    repository_plan = None
    environment_plan = None
    discovery_payload: dict[str, object] | None = None

    if output_backend not in {"persistent", "ephemeral"}:
        raise ValueError("output_backend must be 'persistent' or 'ephemeral'")
    trusted_artifacts = tuple(trusted_artifact_contract)
    if trusted_artifacts and trusted_reference_root is None:
        raise ValueError("trusted_reference_root is required with a trusted host artifact contract")
    if trusted_reference_root is not None and not trusted_artifacts:
        raise ValueError(
            "trusted_reference_root is meaningless without a trusted host artifact contract"
        )
    if trusted_reference_root is not None:
        if trusted_reference_root.is_symlink() or not trusted_reference_root.is_dir():
            raise ValueError("trusted_reference_root must be a regular host-owned directory")

    try:
        paper = resolve_paper(source, workspace / "paper")
        page_count = paper.metadata.get("page_count")
        detail = str(paper.pdf_path)
        if page_count:
            detail += f" ({page_count} page(s))"
        stages.append(StageResult("Paper resolved", "passed", detail))
    except Exception as exc:
        stages.append(StageResult("Paper resolved", "failed", str(exc)))
        return write_failure_report(
            source=source,
            workspace=workspace,
            repository=chosen_repo,
            stages=stages,
        )

    discovery = discover_paper_artifacts(paper)
    discovery_payload = _discovery_payload(discovery)
    write_discovery(discovery, workspace / "artifact-discovery.json")
    top = discovery.repository_candidates[0] if discovery.repository_candidates else None
    top_detail = (
        f"; top candidate score={top.score} ({', '.join(top.reasons) or 'frequency'})"
        if top
        else ""
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
                        "Model-assisted analysis is not configured; set VERIREPRO_LLM_BASE_URL and "
                        "VERIREPRO_LLM_MODEL (plus VERIREPRO_LLM_API_KEY when required), "
                        "or use --no-llm",
                    )
                )
            else:
                write_intelligence(intelligence, workspace / "paper-intelligence.json")
                verified = sum(
                    item.verification in {"verified", "approximate"}
                    for item in intelligence.evidence
                )
                unverified = sum(
                    item.verification == "unverified" for item in intelligence.evidence
                )
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
            stages.append(
                StageResult(
                    "Paper intelligence",
                    "skipped",
                    f"analysis failed safely: {exc}",
                )
            )
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
        return write_failure_report(
            source=source,
            workspace=workspace,
            repository=None,
            stages=stages,
            paper_intelligence=intelligence.to_dict() if intelligence else None,
            artifact_discovery=discovery_payload,
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
        return write_failure_report(
            source=source,
            workspace=workspace,
            repository=chosen_repo,
            stacks=stacks,
            stages=stages,
            paper_intelligence=intelligence.to_dict() if intelligence else None,
            artifact_discovery=discovery_payload,
        )

    declared_contract_items = manifest.declared_metric_count + manifest.declared_artifact_count
    if trusted_artifacts:
        stages.append(
            StageResult(
                "Scientific contract",
                "passed",
                f"host supplied {len(trusted_artifacts)} independent artifact comparison(s); "
                "reference bytes are outside third-party repository authority",
            )
        )
    elif declared_contract_items and manifest.scientific_contract_trusted:
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
                        "no eligible repository entrypoints or model-endpoint configuration",
                    )
                )
        except LLMUnavailableError as exc:
            stages.append(StageResult("Repository execution planned", "skipped", str(exc)))
        except Exception as exc:
            stages.append(
                StageResult(
                    "Repository execution planned",
                    "skipped",
                    f"planning failed safely: {exc}",
                )
            )

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
    elif not run_command and not any(
        stage.name == "Repository execution planned" for stage in stages
    ):
        stages.append(
            StageResult("Repository execution planned", "skipped", "LLM planning disabled")
        )

    network_enabled = _effective_network(manifest.network, allow_network)
    stages.append(
        StageResult(
            "Network policy",
            "passed",
            network_policy_detail(manifest.network, allow_network),
        )
    )

    # Older internal manifest/plan-like fixtures may not carry optional GPU fields.
    # Absence always means CPU-only; compatibility must never grant device access.
    manifest_requests_gpu = bool(getattr(manifest, "gpu", False))
    gpu_likely = bool(getattr(environment_plan, "gpu_likely", False))
    gpu_enabled = _effective_gpu(manifest_requests_gpu, allow_gpu)
    stages.append(
        StageResult(
            "GPU policy",
            "passed",
            gpu_policy_detail(manifest_requests_gpu, allow_gpu, gpu_likely),
        )
    )

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
            preexecution_failed = True
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
            preexecution_failed = True
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
                    f"fixed absolute tolerance={AUTO_METRIC_TOLERANCE}",
                )
            )

    output_dir = workspace / "outputs"
    stages.append(
        StageResult(
            "Output policy",
            "passed",
            output_policy_detail(output_backend),
        )
    )

    execution = execute_experiment(
        execute=execute,
        run_command=run_command,
        preexecution_failed=preexecution_failed,
        repository_url=chosen_repo,
        repository_path=repo,
        dockerfile=dockerfile,
        environment_fingerprint=environment_plan.environment_fingerprint,
        workspace=workspace,
        output_dir=output_dir,
        dataset_dir=dataset_dir,
        model_dir=model_dir if model_artifacts else None,
        output_backend=output_backend,
        network_enabled=network_enabled,
        gpu_enabled=gpu_enabled,
        timeout=timeout,
    )
    stages.extend(execution.stages)
    reproduced_metrics = execution.reproduced_metrics

    verification = verify_results(
        manifest=manifest,
        execute=execute,
        repository_path=repo,
        workspace=workspace,
        output_dir=output_dir,
        paper_metrics=paper_metrics,
        reproduced_metrics=reproduced_metrics,
        metric_specs=metric_specs,
        execution_failed=execution.failed,
        artifact_specs=trusted_artifacts if trusted_artifacts else None,
        artifact_reference_root=trusted_reference_root,
    )
    stages.extend(verification.stages)

    return write_completed_report(
        source=source,
        status=verification.status,
        repository=chosen_repo,
        stacks=stacks,
        stages=stages,
        paper_metrics=paper_metrics,
        reproduced_metrics=reproduced_metrics,
        metric_comparisons=verification.metric_comparisons,
        workspace=workspace,
        paper_intelligence=intelligence.to_dict() if intelligence else None,
        repository_plan=repository_plan.to_dict() if repository_plan else None,
        environment_plan=environment_plan.to_dict(),
        artifact_discovery=discovery_payload,
        artifact_comparisons=verification.artifact_comparisons,
        output_artifacts=verification.output_artifacts,
    )
