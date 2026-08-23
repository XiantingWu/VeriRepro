from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReproductionPlan:
    paper: str
    stages: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_reproduction_plan(paper: str) -> ReproductionPlan:
    paper = paper.strip()
    if not paper:
        raise ValueError("paper reference must not be empty")
    return ReproductionPlan(
        paper=paper,
        stages=(
            "resolve-paper",
            "understand-experiment",
            "discover-repository-and-data",
            "create-docker-environment",
            "download-declared-datasets",
            "execute-experiment",
            "compare-metrics",
            "emit-reproducibility-report",
        ),
    )
