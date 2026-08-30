from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Protocol

from .config import MetricSpec
from .models import ArtifactComparison, MetricComparison

AUTO_METRIC_TOLERANCE = 0.01
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


class _MetricClaimLike(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def value(self) -> float: ...

    @property
    def quote(self) -> str: ...

    @property
    def verification(self) -> str: ...


class _IntelligenceLike(Protocol):
    @property
    def metrics(self) -> Sequence[_MetricClaimLike]: ...


def canonical_auto_metric(name: str) -> str | None:
    key = re.sub(r"\s+", "_", name.strip().lower().replace("-", "_"))
    return _METRIC_CANONICAL.get(key)


def quote_supports_metric_name(canonical: str, quote: str) -> bool:
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


def auto_verdict_metrics(
    intelligence: _IntelligenceLike,
) -> tuple[dict[str, float], tuple[MetricSpec, ...], tuple[str, ...]]:
    """Return deterministic paper metrics that are eligible for automatic verdicts.

    Model-suggested tolerances are never trusted. Only normalized metric families
    with a name supported by the grounded quote are eligible. Conflicting values
    for the same canonical metric are excluded instead of selecting one.
    """
    grouped: dict[str, list[float]] = {}
    excluded: set[str] = set()
    for item in intelligence.metrics:
        if item.verification not in {"verified", "approximate"}:
            continue
        canonical = canonical_auto_metric(item.name)
        if canonical is None:
            excluded.add(item.name)
            continue
        if not quote_supports_metric_name(canonical, item.quote):
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
                tolerance=AUTO_METRIC_TOLERANCE,
            )
        )
    return paper_metrics, tuple(specs), tuple(sorted(excluded))


def effective_network(manifest_requests_network: bool, user_allows_network: bool) -> bool:
    """A repository may request network access, but only the user can authorize it."""
    return bool(manifest_requests_network and user_allows_network)


def effective_gpu(manifest_requests_gpu: bool, user_allows_gpu: bool) -> bool:
    """Repository GPU requests never grant device access without explicit host authorization."""
    return bool(manifest_requests_gpu and user_allows_gpu)


def network_policy_detail(manifest_requests_network: bool, user_allows_network: bool) -> str:
    if manifest_requests_network and user_allows_network:
        return (
            "repository requested network access and the user explicitly authorized --allow-network"
        )
    if manifest_requests_network:
        return "repository requested network access, but it was denied because --allow-network was not provided"
    return "repository did not request network access; Docker networking remains disabled"


def gpu_policy_detail(
    manifest_requests_gpu: bool,
    user_allows_gpu: bool,
    gpu_likely: bool,
) -> str:
    if manifest_requests_gpu and user_allows_gpu:
        return (
            "repository requested GPU access and the user explicitly authorized --allow-gpu; "
            "Docker will request all configured GPU devices"
        )
    if manifest_requests_gpu:
        return "repository requested GPU access, but it was denied because --allow-gpu was not provided"
    if gpu_likely:
        return (
            "CUDA/GPU signals were detected, but the repository manifest did not request GPU access; "
            "Docker remains CPU-only"
        )
    return "repository did not request GPU access; Docker remains CPU-only"


def output_policy_detail(output_backend: str) -> str:
    if output_backend == "ephemeral":
        return (
            "ephemeral bounded tmpfs; experiment file outputs are discarded after the container exits "
            "and never bind-mounted to the host"
        )
    return (
        "persistent run-scoped host bind; post-run indexing remains host-budgeted but the bind "
        "is not a hard filesystem quota"
    )


def final_status(
    *,
    execution_failed: bool,
    metric_comparisons: Sequence[MetricComparison],
    artifact_comparisons: Sequence[ArtifactComparison],
) -> str:
    metric_failed = any(not item.passed for item in metric_comparisons)
    artifact_failed = any(not item.passed for item in artifact_comparisons)
    if execution_failed or metric_failed or artifact_failed:
        return "FAIL"
    if metric_comparisons or artifact_comparisons:
        return "PASS"
    return "PARTIAL"
