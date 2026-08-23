from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_public_ci_does_not_require_trusted_release_evidence() -> None:
    ci = _workflow("ci.yml")
    assert "scripts/release_check.py" in ci
    assert "release_source_check.py" not in ci
    assert "--require-release-evidence" not in ci


def test_publish_workflow_owns_final_evidence_and_source_fingerprint_gates() -> None:
    publish = _workflow("publish.yml")
    assert "python scripts/release_check.py --require-release-evidence" in publish
    assert "python scripts/release_source_check.py" in publish
