from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .models import (
    ArtifactComparison,
    MetricComparison,
    OutputArtifact,
    ReproductionReport,
    StageResult,
)
from .reporting import write_report


def write_failure_report(
    *,
    source: str,
    workspace: Path,
    repository: str | None,
    stages: Sequence[StageResult],
    stacks: tuple[str, ...] = (),
    paper_intelligence: dict[str, object] | None = None,
    artifact_discovery: dict[str, object] | None = None,
) -> ReproductionReport:
    """Persist a terminal pre-execution failure without fabricating result evidence."""
    return write_report(
        ReproductionReport(
            source=source,
            status="FAIL",
            repository=repository,
            stacks=stacks,
            stages=list(stages),
            paper_metrics={},
            reproduced_metrics={},
            comparisons=[],
            workspace=workspace,
            paper_intelligence=paper_intelligence,
            artifact_discovery=artifact_discovery,
        )
    )


def write_completed_report(
    *,
    source: str,
    status: str,
    repository: str,
    stacks: tuple[str, ...],
    stages: Sequence[StageResult],
    paper_metrics: dict[str, float],
    reproduced_metrics: dict[str, float],
    metric_comparisons: Sequence[MetricComparison],
    workspace: Path,
    paper_intelligence: dict[str, object] | None,
    repository_plan: dict[str, object] | None,
    environment_plan: dict[str, object],
    artifact_discovery: dict[str, object] | None,
    artifact_comparisons: Sequence[ArtifactComparison],
    output_artifacts: Sequence[OutputArtifact],
) -> ReproductionReport:
    """Persist the final evidence bundle after execution and verification decisions."""
    return write_report(
        ReproductionReport(
            source=source,
            status=status,
            repository=repository,
            stacks=stacks,
            stages=list(stages),
            paper_metrics=paper_metrics,
            reproduced_metrics=reproduced_metrics,
            comparisons=list(metric_comparisons),
            workspace=workspace,
            paper_intelligence=paper_intelligence,
            repository_plan=repository_plan,
            environment_plan=environment_plan,
            artifact_discovery=artifact_discovery,
            artifact_comparisons=list(artifact_comparisons),
            output_artifacts=list(output_artifacts),
        )
    )
