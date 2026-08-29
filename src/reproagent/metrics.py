from __future__ import annotations

import re

from .config import MetricSpec
from .models import MetricComparison

_MARKER = re.compile(
    r"(?:VERIREPRO|REPROAGENT)_METRIC\s+(?P<name>[A-Za-z0-9_.-]+)\s*=\s*(?P<value>-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_KNOWN = {
    "accuracy": re.compile(r"\baccuracy\b\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(%)?", re.IGNORECASE),
    "f1": re.compile(r"\bf1(?:[-_ ]?score)?\b\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(%)?", re.IGNORECASE),
    "auc": re.compile(r"\b(?:auroc|auc)\b\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(%)?", re.IGNORECASE),
    "precision": re.compile(r"\bprecision\b\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(%)?", re.IGNORECASE),
    "recall": re.compile(r"\brecall\b\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(%)?", re.IGNORECASE),
    "loss": re.compile(r"\bloss\b\s*[:=]?\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE),
}


def _normalize(name: str, value: float, percent: bool = False) -> float:
    if percent or (
        name.lower() in {"accuracy", "f1", "auc", "precision", "recall"} and 1 < value <= 100
    ):
        return round(value / 100.0, 12)
    return value


def extract_output_metrics(text: str) -> dict[str, float]:
    """Extract only explicit VeriRepro metric markers for scientific verdicts.

    Arbitrary training logs frequently contain baseline, validation, ablation,
    or intermediate-epoch numbers. Treating the first ``accuracy:``/``loss:``
    substring as the reproduced result can silently create a false PASS/FAIL.
    Scientific comparisons therefore require an explicit marker emitted by the
    experiment contract::

        VERIREPRO_METRIC accuracy=0.914

    The legacy ``REPROAGENT_METRIC`` prefix remains accepted for compatibility.
    Use :func:`extract_informational_metrics` when best-effort log parsing is
    useful for diagnostics but must not participate in the scientific verdict.
    """
    metrics: dict[str, float] = {}
    for match in _MARKER.finditer(text):
        name = match.group("name").lower()
        metrics[name] = _normalize(name, float(match.group("value")))
    return metrics


def extract_informational_metrics(
    text: str,
    requested: tuple[str, ...] = (),
) -> dict[str, float]:
    """Best-effort metric parsing for diagnostics, never automatic verdicts.

    Callers must explicitly name the metrics they want. This keeps the helper
    useful for UI/debugging without turning unstructured stdout into scientific
    evidence.
    """
    if not requested:
        return {}
    metrics: dict[str, float] = {}
    for name in requested:
        key = name.lower()
        pattern = _KNOWN.get(key)
        if pattern is None:
            continue
        match = pattern.search(text)
        if match:
            percent = len(match.groups()) > 1 and bool(match.group(2))
            metrics[key] = _normalize(key, float(match.group(1)), percent)
    return metrics


def extract_paper_metrics(text: str, requested: tuple[str, ...] = ()) -> dict[str, float]:
    """Extract explicitly requested metric names for informational tooling.

    This helper deliberately does not infer a set of paper metrics when the
    caller supplies no requested names. Whole-paper regex discovery is too
    ambiguous to serve as scientific evidence: a paper may mention many
    baselines, ablations, and percentages. Automated VeriRepro verdicts must
    instead use manifest-authorized expectations or page/quote-grounded paper
    intelligence.
    """
    return extract_informational_metrics(text, requested)


def compare_metrics(
    paper_metrics: dict[str, float],
    reproduced_metrics: dict[str, float],
    specs: tuple[MetricSpec, ...] = (),
) -> list[MetricComparison]:
    tolerances = {spec.name.lower(): spec.tolerance for spec in specs}
    comparisons: list[MetricComparison] = []
    for name, paper in paper_metrics.items():
        key = name.lower()
        if key not in reproduced_metrics:
            continue
        reproduced = reproduced_metrics[key]
        tolerance = float(tolerances.get(key, 0.01))
        difference = reproduced - paper
        comparisons.append(
            MetricComparison(
                name=key,
                paper=paper,
                reproduced=reproduced,
                difference=difference,
                tolerance=tolerance,
                passed=abs(difference) <= tolerance,
            )
        )
    return comparisons
