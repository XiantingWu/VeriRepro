from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PaperReference:
    raw: str
    kind: str
    identifier: str


@dataclass
class PaperDocument:
    reference: PaperReference
    pdf_path: Path
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepositoryEvidence:
    source: str
    page: int | None
    context: str


@dataclass(frozen=True)
class RepositoryCandidate:
    url: str
    score: int
    occurrences: int
    reasons: tuple[str, ...] = ()
    evidence: tuple[RepositoryEvidence, ...] = ()


@dataclass(frozen=True)
class DiscoveryResult:
    github_repositories: tuple[str, ...]
    dataset_urls: tuple[str, ...]
    repository_candidates: tuple[RepositoryCandidate, ...] = ()


@dataclass(frozen=True)
class RepositoryProfile:
    path: Path
    stacks: tuple[str, ...]
    dependency_files: tuple[str, ...]
    manifest_path: Path | None
    suggested_command: str | None
    commit_sha: str | None = None
    python_requirement: str | None = None
    python_source: str | None = None
    cuda_hints: tuple[str, ...] = ()
    dependency_strategy: str = "none"
    fingerprint: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EnvironmentPlan:
    python_version: str
    python_source: str
    python_requirement: str | None
    dependency_strategy: str
    dependency_files: tuple[str, ...]
    commit_sha: str | None
    repository_fingerprint: str | None
    environment_fingerprint: str
    gpu_likely: bool
    cuda_hints: tuple[str, ...]
    reproducibility_grade: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class MetricComparison:
    name: str
    paper: float
    reproduced: float
    difference: float
    tolerance: float
    passed: bool


@dataclass(frozen=True)
class OutputArtifact:
    path: str
    kind: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ArtifactComparison:
    name: str
    kind: str
    reference: str
    reproduced: str
    score: float
    threshold: float
    passed: bool
    detail: str


@dataclass
class ExperimentResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


@dataclass
class ReproductionReport:
    source: str
    status: str
    repository: str | None
    stacks: tuple[str, ...]
    stages: list[StageResult]
    paper_metrics: dict[str, float]
    reproduced_metrics: dict[str, float]
    comparisons: list[MetricComparison]
    workspace: Path
    paper_intelligence: dict[str, Any] | None = None
    repository_plan: dict[str, Any] | None = None
    environment_plan: dict[str, Any] | None = None
    artifact_discovery: dict[str, Any] | None = None
    artifact_comparisons: list[ArtifactComparison] = field(default_factory=list)
    output_artifacts: list[OutputArtifact] = field(default_factory=list)
    report_json: Path | None = None
    report_markdown: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = REPORT_SCHEMA_VERSION
        payload["workspace"] = str(self.workspace)
        payload["report_json"] = str(self.report_json) if self.report_json else None
        payload["report_markdown"] = str(self.report_markdown) if self.report_markdown else None
        return payload
