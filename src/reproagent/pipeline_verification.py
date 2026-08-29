from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .artifacts import compare_artifacts, index_outputs, write_artifact_results
from .config import ArtifactSpec, MetricSpec, ReproManifest
from .metrics import compare_metrics
from .models import ArtifactComparison, MetricComparison, OutputArtifact, StageResult
from .pipeline_policy import final_status


@dataclass(frozen=True)
class VerificationOutcome:
    stages: tuple[StageResult, ...]
    output_artifacts: tuple[OutputArtifact, ...]
    artifact_comparisons: tuple[ArtifactComparison, ...]
    metric_comparisons: tuple[MetricComparison, ...]
    output_index_failed: bool
    failed: bool
    status: str


def verify_results(
    *,
    manifest: ReproManifest,
    execute: bool,
    repository_path: Path,
    workspace: Path,
    output_dir: Path,
    paper_metrics: dict[str, float],
    reproduced_metrics: dict[str, float],
    metric_specs: tuple[MetricSpec, ...],
    execution_failed: bool,
    artifact_specs: tuple[ArtifactSpec, ...] | None = None,
    artifact_reference_root: Path | None = None,
) -> VerificationOutcome:
    """Index outputs and evaluate only evidence-authorized scientific comparisons.

    Repository-authored artifact contracts use the repository as their reference
    root. A trusted host caller may instead pass an explicit artifact contract
    and a separate reference root; this keeps benchmark-owned scientific truth
    outside third-party repository authority.
    """
    stages: list[StageResult] = []
    effective_artifacts = manifest.artifacts if artifact_specs is None else artifact_specs
    effective_reference_root = (
        repository_path if artifact_reference_root is None else artifact_reference_root
    )
    output_artifacts: tuple[OutputArtifact, ...] = ()
    artifact_comparisons: tuple[ArtifactComparison, ...] = ()
    output_index_failed = False
    failed = bool(execution_failed)

    try:
        output_artifacts = tuple(index_outputs(output_dir))
        if output_artifacts:
            counts: dict[str, int] = {}
            for item in output_artifacts:
                counts[item.kind] = counts.get(item.kind, 0) + 1
            summary = ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))
            stages.append(
                StageResult(
                    "Outputs indexed",
                    "passed",
                    f"{len(output_artifacts)} artifact(s): {summary}",
                )
            )
        else:
            stages.append(
                StageResult(
                    "Outputs indexed",
                    "skipped",
                    "experiment produced no persisted output artifacts",
                )
            )
    except Exception as exc:
        output_index_failed = True
        failed = True
        stages.append(
            StageResult(
                "Outputs indexed",
                "failed",
                f"host-side output indexing failed safely: {exc}",
            )
        )

    if effective_artifacts and execute and not output_index_failed:
        try:
            artifact_comparisons = tuple(
                compare_artifacts(effective_artifacts, effective_reference_root, output_dir)
            )
            write_artifact_results(
                artifact_comparisons,
                output_artifacts,
                workspace / "artifact-results.json",
            )
            artifact_passed = sum(item.passed for item in artifact_comparisons)
            all_passed = artifact_passed == len(artifact_comparisons)
            if not all_passed:
                failed = True
            stages.append(
                StageResult(
                    "Artifacts compared",
                    "passed" if all_passed else "failed",
                    f"{artifact_passed}/{len(artifact_comparisons)} host-authorized figure/table/file artifact(s) matched",
                )
            )
        except Exception as exc:
            artifact_comparisons = ()
            failed = True
            stages.append(
                StageResult(
                    "Artifact verification safety",
                    "failed",
                    f"host-side artifact verification failed safely: {exc}",
                )
            )
    elif effective_artifacts and output_index_failed:
        stages.append(
            StageResult(
                "Artifacts compared",
                "skipped",
                "output indexing failed its host safety budget; artifact comparisons were not attempted",
            )
        )
    elif effective_artifacts:
        detail = (
            "execution disabled; host-authorized artifact comparisons were not run"
            if not execute
            else "execution produced no safely indexable artifact comparison surface"
        )
        stages.append(StageResult("Artifacts compared", "skipped", detail))
    else:
        if output_artifacts:
            write_artifact_results((), output_artifacts, workspace / "artifact-results.json")
        stages.append(
            StageResult(
                "Artifacts compared",
                "skipped",
                "no host-authorized artifact comparison contract was available",
            )
        )

    metric_comparisons = tuple(compare_metrics(paper_metrics, reproduced_metrics, metric_specs))
    if metric_comparisons:
        passed = sum(item.passed for item in metric_comparisons)
        all_passed = passed == len(metric_comparisons)
        if not all_passed:
            failed = True
        stages.append(
            StageResult(
                "Results compared",
                "passed" if all_passed else "failed",
                f"{passed}/{len(metric_comparisons)} evidence-authorized metric(s) within tolerance",
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

    status = final_status(
        execution_failed=failed,
        metric_comparisons=metric_comparisons,
        artifact_comparisons=artifact_comparisons,
    )
    return VerificationOutcome(
        stages=tuple(stages),
        output_artifacts=output_artifacts,
        artifact_comparisons=artifact_comparisons,
        metric_comparisons=metric_comparisons,
        output_index_failed=output_index_failed,
        failed=failed,
        status=status,
    )
