from reproagent.config import MetricSpec
from reproagent.metrics import (
    compare_metrics,
    extract_informational_metrics,
    extract_output_metrics,
)


def test_output_metrics_require_explicit_marker_and_normalize_percentages():
    text = "accuracy: 99\nVERIREPRO_METRIC accuracy=91.4\nREPROAGENT_METRIC loss=-0.25"
    assert extract_output_metrics(text) == {"accuracy": 0.914, "loss": -0.25}


def test_informational_metrics_are_opt_in():
    text = "accuracy: 87.5% loss=0.42"
    assert extract_informational_metrics(text) == {}
    assert extract_informational_metrics(text, ("accuracy", "loss")) == {
        "accuracy": 0.875,
        "loss": 0.42,
    }


def test_compare_metrics_honors_metric_specific_tolerance_and_missing_values():
    specs = (MetricSpec(name="accuracy", paper=0.9, tolerance=0.02),)
    comparisons = compare_metrics(
        {"accuracy": 0.9, "loss": 0.2},
        {"accuracy": 0.915},
        specs,
    )
    assert len(comparisons) == 1
    assert comparisons[0].name == "accuracy"
    assert comparisons[0].passed is True
    assert comparisons[0].tolerance == 0.02
