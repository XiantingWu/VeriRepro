from __future__ import annotations

import math
from typing import Any, Iterable

_PUBLIC_MODEL_USAGE_FIELDS = (
    "request_model",
    "response_model",
    "duration_seconds",
    "request_count",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "cost_usd",
    "error",
)
_INTEGER_FIELDS = (
    "request_count",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
    "reasoning_tokens",
)


def _safe_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _safe_nonnegative_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def public_model_usage(usage: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a non-secret, bounded telemetry snapshot for machine evidence.

    Endpoint URLs, API keys, request prompts, response content, headers, and any
    future unrecognized client fields are intentionally dropped.
    """
    if not isinstance(usage, dict):
        return None
    result: dict[str, Any] = {}
    for key in _PUBLIC_MODEL_USAGE_FIELDS:
        if key not in usage:
            continue
        value = usage.get(key)
        if key in _INTEGER_FIELDS:
            result[key] = _safe_nonnegative_int(value)
        elif key in {"duration_seconds", "cost_usd"}:
            result[key] = _safe_nonnegative_float(value)
        elif key in {"request_model", "response_model", "error"}:
            if value is None:
                result[key] = None
            elif isinstance(value, str):
                result[key] = value[:300]
    return result or None


def aggregate_model_usage(
    usages: Iterable[dict[str, Any] | None],
) -> tuple[float | None, dict[str, Any] | None]:
    """Aggregate sanitized usage without inventing unavailable provider data."""
    snapshots = [snapshot for usage in usages if (snapshot := public_model_usage(usage))]
    if not snapshots:
        return None, None

    costs = [
        value
        for item in snapshots
        if isinstance((value := item.get("cost_usd")), (int, float))
    ]
    cost_total = round(sum(float(value) for value in costs), 10) if costs else None

    token_usage: dict[str, Any] = {"calls_with_telemetry": len(snapshots)}
    for key in _INTEGER_FIELDS:
        values = [value for item in snapshots if isinstance((value := item.get(key)), int)]
        token_usage[key] = sum(values) if values else None
    durations = [
        float(value)
        for item in snapshots
        if isinstance((value := item.get("duration_seconds")), (int, float))
    ]
    token_usage["duration_seconds"] = round(sum(durations), 6) if durations else None
    return cost_total, token_usage
