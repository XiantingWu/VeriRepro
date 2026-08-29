from __future__ import annotations

from typing import Any

import pytest

from reproagent.usage import aggregate_model_usage, public_model_usage


def test_public_model_usage_returns_none_for_non_mapping_payloads() -> None:
    assert public_model_usage(None) is None
    assert public_model_usage(["prompt_tokens", 5]) is None
    assert public_model_usage("usage") is None


def test_public_model_usage_returns_none_for_empty_payload() -> None:
    assert public_model_usage({}) is None


def test_public_model_usage_keeps_only_public_fields() -> None:
    usage = {
        "request_model": "model-a",
        "response_model": "model-b",
        "duration_seconds": 1.5,
        "request_count": 2,
        "prompt_tokens": 100,
        "completion_tokens": 40,
        "total_tokens": 140,
        "cached_tokens": 10,
        "reasoning_tokens": 8,
        "cost_usd": 0.0025,
        "error": None,
        # Secret/unrecognized fields must never leak into telemetry.
        "api_key": "sk-super-secret",
        "endpoint": "https://internal.example/v1",
        "prompt": "the raw prompt text",
        "response": "the raw completion",
        "headers": {"authorization": "Bearer x"},
    }
    snapshot = public_model_usage(usage)
    assert snapshot == {
        "request_model": "model-a",
        "response_model": "model-b",
        "duration_seconds": 1.5,
        "request_count": 2,
        "prompt_tokens": 100,
        "completion_tokens": 40,
        "total_tokens": 140,
        "cached_tokens": 10,
        "reasoning_tokens": 8,
        "cost_usd": 0.0025,
        "error": None,
    }


def test_public_model_usage_truncates_long_strings() -> None:
    snapshot = public_model_usage({"error": "e" * 500, "request_model": "m" * 301})
    assert snapshot is not None
    assert len(snapshot["error"]) == 300
    assert len(snapshot["request_model"]) == 300


def test_public_model_usage_rejects_boolean_counts_and_costs() -> None:
    snapshot = public_model_usage(
        {
            "prompt_tokens": True,
            "completion_tokens": False,
            "cost_usd": True,
            "duration_seconds": False,
            "request_count": True,
        }
    )
    assert snapshot == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "cost_usd": None,
        "duration_seconds": None,
        "request_count": None,
    }


@pytest.mark.parametrize("bad", [-1, "-3", "many", object()])
def test_public_model_usage_rejects_malformed_integer_fields(bad: Any) -> None:
    assert public_model_usage({"prompt_tokens": bad}) == {"prompt_tokens": None}


def test_public_model_usage_truncates_float_token_counts_toward_zero() -> None:
    # Fractional token counts truncate toward zero; every negative value,
    # including fractional values in (-1, 0), must be rejected.
    assert public_model_usage({"prompt_tokens": 2.9}) == {"prompt_tokens": 2}
    assert public_model_usage({"prompt_tokens": -1}) == {"prompt_tokens": None}
    assert public_model_usage({"prompt_tokens": -0.5}) == {"prompt_tokens": None}


def test_public_model_usage_coerces_numeric_strings() -> None:
    snapshot = public_model_usage({"prompt_tokens": "12", "cost_usd": "0.5"})
    assert snapshot == {"prompt_tokens": 12, "cost_usd": 0.5}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -0.01, "oops", None])
def test_public_model_usage_rejects_malformed_float_fields(bad: Any) -> None:
    snapshot = public_model_usage({"cost_usd": bad, "duration_seconds": bad})
    assert snapshot == {"cost_usd": None, "duration_seconds": None}


def test_public_model_usage_drops_non_string_model_fields() -> None:
    assert public_model_usage({"request_model": 42}) is None
    assert public_model_usage({"response_model": ["a"]}) is None
    assert public_model_usage({"error": {"code": 7}}) is None


def test_aggregate_model_usage_without_telemetry_is_all_none() -> None:
    assert aggregate_model_usage([]) == (None, None)
    assert aggregate_model_usage([None]) == (None, None)
    assert aggregate_model_usage([{}, {"unrelated": "field"}]) == (None, None)


def test_aggregate_model_usage_sums_costs_and_token_families() -> None:
    usages: list[dict[str, Any] | None] = [
        {
            "request_model": "model-a",
            "cost_usd": 0.1,
            "request_count": 1,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "duration_seconds": 1.25,
        },
        {
            "response_model": "model-b",
            "cost_usd": 0.2,
            "prompt_tokens": "30",
            "cached_tokens": 7,
        },
        None,
        {"ignored": True},
    ]
    cost_total, token_usage = aggregate_model_usage(usages)

    assert cost_total == 0.3
    assert token_usage == {
        "calls_with_telemetry": 2,
        "request_count": 1,
        "prompt_tokens": 40,
        "completion_tokens": 5,
        "total_tokens": 15,
        "cached_tokens": 7,
        "reasoning_tokens": None,
        "duration_seconds": 1.25,
    }


def test_aggregate_model_usage_sums_durations_across_snapshots() -> None:
    _cost, token_usage = aggregate_model_usage(
        [{"duration_seconds": 1.5}, {"duration_seconds": 2}, {"duration_seconds": 0.25}]
    )
    assert token_usage is not None
    assert token_usage["duration_seconds"] == 3.75


def test_aggregate_model_usage_reports_none_for_absent_families() -> None:
    cost_total, token_usage = aggregate_model_usage([{"request_model": "only-model"}])
    assert cost_total is None
    assert token_usage == {
        "calls_with_telemetry": 1,
        "request_count": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "cached_tokens": None,
        "reasoning_tokens": None,
        "duration_seconds": None,
    }


def test_aggregate_model_usage_excludes_non_finite_costs() -> None:
    cost_total, token_usage = aggregate_model_usage(
        [{"cost_usd": float("nan"), "prompt_tokens": 4}, {"cost_usd": float("inf")}]
    )
    assert cost_total is None
    assert token_usage is not None
    assert token_usage["prompt_tokens"] == 4
    assert token_usage["calls_with_telemetry"] == 2


def test_aggregate_model_usage_rounds_away_floating_point_drift() -> None:
    cost_total, _token_usage = aggregate_model_usage(
        [{"cost_usd": 0.1}, {"cost_usd": 0.2}, {"cost_usd": 0.3}]
    )
    assert cost_total == 0.6


@pytest.mark.parametrize("value", [-0.5, "-0.5", "-2", float("inf"), "inf", "-0.0001"])
def test_public_model_usage_rejects_negative_fractional_and_nonfinite_integers(
    value: Any,
) -> None:
    snapshot = public_model_usage({"prompt_tokens": value})
    assert snapshot is not None
    assert snapshot["prompt_tokens"] is None
