from pathlib import Path
from types import SimpleNamespace

from reproagent.intelligence import (
    Ambiguity,
    EvidenceAnchor,
    PaperIntelligence,
    _canonical_field,
    _complete_ambiguity_audit,
    _normalize_metric,
    _numbers_equivalent,
    _quote_supports_evidence_value,
    _quote_supports_metric_value,
    _verify_quote,
    analyze_paper,
    verified_metric_values,
)
from reproagent.models import PaperDocument, PaperReference


def _paper(*pages: str) -> PaperDocument:
    return PaperDocument(
        reference=PaperReference(raw="demo.pdf", kind="local-pdf", identifier="demo.pdf"),
        pdf_path=Path("demo.pdf"),
        text="\n".join(pages),
        metadata={"pages": list(pages), "page_count": len(pages)},
    )


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.config = SimpleNamespace(model="fixture-model")
        self.user_prompt = ""

    def complete_json(self, *, system: str, user: str):
        assert "UNTRUSTED DATA" in system
        self.user_prompt = user
        return self.payload


def test_canonical_field_normalizes_aliases():
    assert _canonical_field("Learning-Rate") == "learning_rate"
    assert _canonical_field("GPU") == "hardware"


def test_reproduction_completeness_counts_grounded_required_fields_only():
    intelligence = PaperIntelligence(
        task="classification",
        canonical_repository=None,
        evidence=(
            EvidenceAnchor("dataset", "demo", 1, "dataset demo", "high", "verified"),
            EvidenceAnchor("lr", "1e-3", 2, "lr 1e-3", "high", "approximate"),
            EvidenceAnchor("optimizer", "", 2, "optimizer", "low", "unverified"),
        ),
        metrics=(),
        ambiguities=(),
        model="test",
    )
    assert intelligence.grounded_claim_count == 2
    assert intelligence.reproduction_completeness == 2 / 13


def test_quote_verification_exact_approximate_and_invalid_page():
    pages = ["We train the model on CIFAR-10 with Adam for 50 epochs."]
    assert _verify_quote(pages, 1, "CIFAR-10 with Adam") == "verified"
    assert (
        _verify_quote(
            pages,
            1,
            "We train model on CIFAR-10 with Adam for fifty epochs",
        )
        == "approximate"
    )
    assert _verify_quote(pages, 2, "CIFAR-10") == "unverified"
    assert _verify_quote(pages, None, "CIFAR-10") == "unverified"


def test_evidence_value_requires_quote_support_including_numeric_scale():
    assert _quote_supports_evidence_value("AdamW", "Optimizer: AdamW") is True
    assert _quote_supports_evidence_value("0.914", "accuracy was 91.4%") is True
    assert _quote_supports_evidence_value("0.914", "accuracy was 87.0%") is False
    assert _quote_supports_evidence_value("model", "the model") is True
    assert _quote_supports_evidence_value("architecture", "the model architecture") is True
    assert _quote_supports_evidence_value("", "anything") is False


def test_number_equivalence_handles_percent_and_fraction_forms():
    assert _numbers_equivalent(91.4, True, 0.914, False) is True
    assert _numbers_equivalent(0.914, False, 91.4, False) is True
    assert _numbers_equivalent(0.9, False, 0.8, False) is False


def test_metric_normalization_and_quote_value_grounding():
    value, tolerance = _normalize_metric("accuracy", 91.4, 1.0)
    assert value == 0.914
    assert tolerance == 0.01
    assert _quote_supports_metric_value("accuracy", value, "Accuracy: 91.4%") is True
    assert _quote_supports_metric_value("accuracy", value, "Accuracy: 88.2%") is False


def test_ambiguity_audit_fills_missing_required_fields_without_duplicates():
    evidence = [
        EvidenceAnchor("dataset", "CIFAR-10", 1, "CIFAR-10", "high", "verified"),
    ]
    ambiguities = [
        Ambiguity("optimizer", "not specified", "medium", "inspect code"),
    ]
    completed = _complete_ambiguity_audit(evidence, ambiguities)
    fields = [_canonical_field(item.field) for item in completed]
    assert fields.count("optimizer") == 1
    assert "dataset" not in fields
    assert "random_seed" in fields
    assert next(item for item in completed if item.field == "random_seed").severity == "high"


def test_analyze_paper_verifies_claims_normalizes_metrics_and_rejects_unlisted_repo():
    paper = _paper(
        "We train on CIFAR-10. The learning rate is 0.01. Accuracy: 91.4%.",
        "Implementation details use AdamW for 50 epochs.",
    )
    client = _Client(
        {
            "task": "classification",
            "canonical_repository": "https://github.com/example/not-allowed",
            "evidence": [
                {
                    "field": "dataset",
                    "value": "CIFAR-10",
                    "page": 1,
                    "quote": "We train on CIFAR-10",
                    "confidence": "high",
                },
                {
                    "field": "learning_rate",
                    "value": "0.001",
                    "page": 1,
                    "quote": "The learning rate is 0.01",
                    "confidence": "high",
                },
                "ignore-me",
            ],
            "metrics": [
                {
                    "name": "accuracy",
                    "value": 91.4,
                    "tolerance": 1.0,
                    "page": 1,
                    "quote": "Accuracy: 91.4%",
                },
                {
                    "name": "accuracy",
                    "value": "not-a-number",
                    "page": 1,
                    "quote": "Accuracy: 91.4%",
                },
            ],
            "ambiguities": [
                {
                    "field": "random_seed",
                    "issue": "seed not stated",
                    "severity": "high",
                    "recommendation": "inspect code",
                }
            ],
        }
    )

    result = analyze_paper(
        paper,
        ("https://github.com/example/official",),
        client=client,
    )

    assert result is not None
    assert result.model == "fixture-model"
    assert result.canonical_repository is None
    assert result.evidence[0].verification == "verified"
    assert result.evidence[1].verification == "unverified"
    assert result.metrics[0].value == 0.914
    assert result.metrics[0].tolerance == 0.01
    assert result.metrics[0].verification == "verified"
    assert verified_metric_values(result) == {"accuracy": 0.914}
    assert "https://github.com/example/official" in client.user_prompt
    assert any(item.field == "random_seed" for item in result.ambiguities)


def test_analyze_paper_accepts_only_candidate_canonical_repository():
    repository = "https://github.com/example/official"
    client = _Client(
        {
            "task": None,
            "canonical_repository": repository,
            "evidence": [],
            "metrics": [],
            "ambiguities": [],
        }
    )
    result = analyze_paper(_paper("paper text"), (repository,), client=client)
    assert result is not None
    assert result.canonical_repository == repository
