from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from reproagent.models import (
    REPORT_SCHEMA_VERSION,
    ArtifactComparison,
    MetricComparison,
    OutputArtifact,
    ReproductionReport,
    StageResult,
)
from reproagent.reporting import _cell, _clip, render_markdown, write_report


def _report(workspace: Path, **overrides: Any) -> ReproductionReport:
    values: dict[str, Any] = {
        "source": "arXiv:2401.00001",
        "status": "FAIL",
        "repository": "/data/repo-under-test",
        "stacks": ("python", "pytorch"),
        "stages": [
            StageResult("Collect paper metrics", "passed", "3 metric(s) grounded in quotes"),
            StageResult("Execute experiment", "failed", "exit code 1"),
            StageResult("Outputs indexed", "skipped", "no artifacts produced"),
        ],
        "paper_metrics": {"accuracy": 0.9},
        "reproduced_metrics": {"accuracy": 0.85},
        "comparisons": [
            MetricComparison(
                name="accuracy",
                paper=0.9,
                reproduced=0.85,
                difference=-0.05,
                tolerance=0.02,
                passed=False,
            )
        ],
        "workspace": workspace,
    }
    values.update(overrides)
    return ReproductionReport(**values)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def test_clip_collapses_whitespace_and_preserves_short_text() -> None:
    assert _clip("  alpha\n beta\tgamma  ") == "alpha beta gamma"


def test_clip_truncates_long_text_with_ellipsis() -> None:
    clipped = _clip("x" * 500)
    assert len(clipped) == 180
    assert clipped.endswith("…")
    assert clipped.startswith("x" * 179)


def test_cell_escapes_table_pipes_after_clipping() -> None:
    assert _cell("a|b") == "a\\|b"
    long_pipe_text = "|" + "y" * 300
    rendered = _cell(long_pipe_text)
    assert len(rendered) == 181  # 180 chars of clipped text, with the pipe escaped
    assert rendered.startswith("\\|")


# ---------------------------------------------------------------------------
# Header and stage rendering
# ---------------------------------------------------------------------------


def test_markdown_header_renders_source_status_and_stacks(tmp_path: Path) -> None:
    markdown = render_markdown(_report(tmp_path))
    assert markdown.startswith("# VeriRepro Reproducibility Report")
    assert "- **Source:** arXiv:2401.00001" in markdown
    assert "- **Repository:** /data/repo-under-test" in markdown
    assert "- **Status:** FAIL" in markdown
    assert "- **Detected stack:** python, pytorch" in markdown


def test_markdown_reports_missing_repository_and_unknown_stacks(tmp_path: Path) -> None:
    report = _report(tmp_path, repository=None, stacks=())
    markdown = render_markdown(report)
    assert "- **Repository:** not found" in markdown
    assert "- **Detected stack:** unknown" in markdown


def test_markdown_stage_symbols_cover_known_and_unknown_statuses(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        stages=[
            StageResult("Fetch paper", "passed", "ok"),
            StageResult("Run container", "failed", "boom"),
            StageResult("Index outputs", "skipped", "nothing"),
            StageResult("Mystery stage", "insufficient_evidence", "cannot decide"),
        ],
    )
    markdown = render_markdown(report)
    assert "- ✓ **Fetch paper** — ok" in markdown
    assert "- ✗ **Run container** — boom" in markdown
    assert "- ○ **Index outputs** — nothing" in markdown
    # Unknown statuses must not borrow the success symbol.
    assert "- • **Mystery stage** — cannot decide" in markdown


def test_insufficient_evidence_status_is_never_rendered_as_pass(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        status="PARTIAL",
        stages=[
            StageResult("Results compared", "skipped", "no comparable metrics"),
            StageResult("Artifacts compared", "skipped", "no declared artifacts"),
        ],
        comparisons=[],
        artifact_comparisons=[],
        output_artifacts=[],
    )
    markdown = render_markdown(report)

    assert "- **Status:** PARTIAL" in markdown
    assert "PASS" not in markdown
    assert "✓" not in markdown


# ---------------------------------------------------------------------------
# Optional intelligence / discovery sections
# ---------------------------------------------------------------------------


def test_minimal_report_renders_empty_section_placeholders(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        comparisons=[],
        artifact_comparisons=[],
        output_artifacts=[],
        paper_intelligence=None,
        artifact_discovery=None,
        repository_plan=None,
        environment_plan=None,
    )
    markdown = render_markdown(report)
    assert "## Paper intelligence" not in markdown
    assert "## Artifact discovery" not in markdown
    assert "## Repository execution plan" not in markdown
    assert "## Environment provenance" not in markdown
    assert "No declared figure/table/file comparisons were evaluated." in markdown
    assert "No comparable metrics were produced." in markdown


def test_paper_intelligence_section_renders_evidence_and_ambiguities(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        paper_intelligence={
            "task": "image classification on CIFAR-10",
            "model": "resnet-50",
            "reproduction_completeness": 0.875,
            "evidence": [
                {
                    "field": "learning rate",
                    "value": "3e-4",
                    "page": 6,
                    "verification": "verified",
                    "quote": "lr | 3e-4 schedule",
                },
                {"field": "batch size", "value": "256"},
            ],
            "ambiguities": [
                {
                    "severity": "high",
                    "field": "epochs",
                    "issue": "training length not stated",
                    "recommendation": "ask authors for config",
                }
            ],
        },
    )
    markdown = render_markdown(report)

    assert "**Task:** image classification on CIFAR-10" in markdown
    assert "**Model:** `resnet-50`" in markdown
    assert "**Critical-field completeness:** 88%" in markdown
    assert "| Field | Value | Page | Verification | Evidence |" in markdown
    assert "| learning rate | 3e-4 | 6 | VERIFIED | lr \\| 3e-4 schedule |" in markdown
    assert "| batch size | 256 | — | UNVERIFIED |  |" in markdown
    assert "| Severity | Field | Issue | Recommended action |" in markdown
    assert "| HIGH | epochs | training length not stated | ask authors for config |" in markdown


def test_paper_intelligence_defaults_for_sparse_payloads(tmp_path: Path) -> None:
    report = _report(tmp_path, paper_intelligence={"evidence": [], "ambiguities": []})
    markdown = render_markdown(report)
    assert "**Model:** `unknown`" in markdown
    assert "**Critical-field completeness:**" not in markdown
    assert "No structured evidence claims were returned." in markdown
    assert (
        "No reproduction-critical ambiguities were identified by the configured model." in markdown
    )


def test_artifact_discovery_section_ranks_candidates(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        artifact_discovery={
            "repository_candidates": [
                {
                    "url": "https://github.com/example/repo",
                    "score": 9,
                    "occurrences": 4,
                    "reasons": ["abstract mention", "footnote"],
                },
                {"url": "https://github.com/example/other", "score": 2, "occurrences": 1},
            ]
        },
    )
    markdown = render_markdown(report)
    assert "| Rank | Repository | Score | Occurrences | Evidence signals |" in markdown
    assert (
        "| 1 | https://github.com/example/repo | 9 | 4 | abstract mention, footnote |" in markdown
    )
    assert "| 2 | https://github.com/example/other | 2 | 1 | frequency |" in markdown


def test_artifact_discovery_without_candidates_is_explicit(tmp_path: Path) -> None:
    report = _report(tmp_path, artifact_discovery={"repository_candidates": []})
    markdown = render_markdown(report)
    assert "No GitHub repository candidates were discovered." in markdown


# ---------------------------------------------------------------------------
# Plan sections
# ---------------------------------------------------------------------------


def test_repository_plan_section_renders_all_fields(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        repository_plan={
            "verification": "verified",
            "entrypoint": "python reproduce.py",
            "command": "python train.py --epochs 3",
            "evidence_file": "plan-evidence.json",
            "rationale": "entrypoint declared in README installation section",
            "evidence_quote": "run `python reproduce.py` to train",
        },
    )
    markdown = render_markdown(report)
    assert "## Repository execution plan" in markdown
    assert "- **Verification:** VERIFIED" in markdown
    assert "- **Entrypoint:** `python reproduce.py`" in markdown
    assert "- **Command:** `python train.py --epochs 3`" in markdown
    assert "- **Evidence file:** `plan-evidence.json`" in markdown
    assert "- **Rationale:** entrypoint declared in README installation section" in markdown
    assert "- **Repository evidence:** run `python reproduce.py` to train" in markdown


def test_repository_plan_placeholders_when_fields_missing(tmp_path: Path) -> None:
    report = _report(tmp_path, repository_plan={"verification": "unverified"})
    markdown = render_markdown(report)
    assert "- **Verification:** UNVERIFIED" in markdown
    assert "- **Entrypoint:** `none`" in markdown
    assert "- **Command:** `rejected / unavailable`" in markdown
    assert "- **Evidence file:** `none`" in markdown
    assert "- **Repository evidence:**" not in markdown


def test_environment_plan_section_renders_provenance_and_warnings(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        environment_plan={
            "python_version": "3.11.9",
            "python_source": "docker-image",
            "python_requirement": ">=3.10,<3.12",
            "dependency_strategy": "constraints-file",
            "commit_sha": "abc123",
            "repository_fingerprint": "repo-fp-1",
            "environment_fingerprint": "env-fp-1",
            "reproducibility_grade": "strong",
            "gpu_likely": True,
            "warnings": ["no lockfile found", "pinned CUDA version missing"],
        },
    )
    markdown = render_markdown(report)
    assert "- **Resolved Python:** `3.11.9`" in markdown
    assert "- **Python source:** `docker-image`" in markdown
    assert "- **Repository requirement:** `>=3.10,<3.12`" in markdown
    assert "- **Dependency strategy:** `constraints-file`" in markdown
    assert "- **Repository commit:** `abc123`" in markdown
    assert "- **Repository fingerprint:** `repo-fp-1`" in markdown
    assert "- **Environment fingerprint:** `env-fp-1`" in markdown
    assert "- **Reproducibility grade:** **STRONG**" in markdown
    assert "- **GPU likely:** `True`" in markdown
    assert "### Environment warnings" in markdown
    assert "- no lockfile found" in markdown
    assert "- pinned CUDA version missing" in markdown


def test_environment_plan_hides_empty_warnings(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        environment_plan={
            "python_version": "3.11.9",
            "python_source": "host",
            "reproducibility_grade": "weak",
            "gpu_likely": False,
            "warnings": [],
        },
    )
    markdown = render_markdown(report)
    assert "### Environment warnings" not in markdown
    assert "- **Reproducibility grade:** **WEAK**" in markdown
    assert "- **GPU likely:** `False`" in markdown


# ---------------------------------------------------------------------------
# Evidence tables
# ---------------------------------------------------------------------------


def test_artifact_comparison_rows_render_scores_and_verdicts(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        artifact_comparisons=[
            ArtifactComparison(
                name="fig1",
                kind="figure",
                reference="fig1.png",
                reproduced="fig1.png",
                score=1.0,
                threshold=0.95,
                passed=True,
                detail="SHA-256 match",
            ),
            ArtifactComparison(
                name="tbl|1",
                kind="table",
                reference="tbl.csv",
                reproduced="tbl.csv",
                score=0.5,
                threshold=0.95,
                passed=False,
                detail="cell agreement=2/4 (0.5000)",
            ),
        ],
    )
    markdown = render_markdown(report)
    assert "| Artifact | Type | Score | Threshold | Result | Detail |" in markdown
    assert "| fig1 | figure | 1.0000 | 0.9500 | PASS | SHA-256 match |" in markdown
    assert "| tbl\\|1 | table | 0.5000 | 0.9500 | FAIL | cell agreement=2/4 (0.5000) |" in markdown


def test_output_inventory_rows_render_truncated_hashes(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        output_artifacts=[
            OutputArtifact(
                path="figures/fig.png",
                kind="figure",
                size_bytes=2048,
                sha256="0123456789abcdef" + "0" * 48,
            )
        ],
    )
    markdown = render_markdown(report)
    assert "| Path | Type | Bytes | SHA-256 |" in markdown
    assert "| `figures/fig.png` | figure | 2048 | `0123456789abcdef…` |" in markdown


def test_metric_rows_render_signed_differences_and_verdicts(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        comparisons=[
            MetricComparison(
                name="accuracy",
                paper=0.9,
                reproduced=0.915,
                difference=0.015,
                tolerance=0.02,
                passed=True,
            ),
            MetricComparison(
                name="loss", paper=0.5, reproduced=0.7, difference=0.2, tolerance=0.05, passed=False
            ),
        ],
    )
    markdown = render_markdown(report)
    assert "| Metric | Paper | Reproduced | Difference | Tolerance | Result |" in markdown
    assert "| accuracy | 0.9 | 0.915 | +0.015 | 0.02 | PASS |" in markdown
    assert "| loss | 0.5 | 0.7 | +0.2 | 0.05 | FAIL |" in markdown


# ---------------------------------------------------------------------------
# write_report persistence
# ---------------------------------------------------------------------------


def test_write_report_persists_json_and_markdown_with_schema_version(tmp_path: Path) -> None:
    report = _report(tmp_path)
    returned = write_report(report)

    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    assert returned is report
    assert report.report_json == json_path
    assert report.report_markdown == markdown_path
    assert json_path.is_file() and markdown_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == REPORT_SCHEMA_VERSION == 1
    assert payload["status"] == "FAIL"
    assert payload["workspace"] == str(tmp_path)
    assert payload["report_json"] == str(json_path)
    assert payload["comparisons"][0]["name"] == "accuracy"

    assert markdown_path.read_text(encoding="utf-8") == render_markdown(report)


def test_write_report_output_is_byte_deterministic(tmp_path: Path) -> None:
    first_report = _report(tmp_path)
    second_report = copy.deepcopy(first_report)

    first_paths = (write_report(first_report).report_json, first_report.report_markdown)
    second_paths = (write_report(second_report).report_json, second_report.report_markdown)

    assert first_paths[0].read_bytes() == second_paths[0].read_bytes()
    assert first_paths[1].read_bytes() == second_paths[1].read_bytes()


def test_write_report_creates_missing_workspace_directories(tmp_path: Path) -> None:
    workspace = tmp_path / "runs" / "case-1"
    report = _report(workspace)
    write_report(report)
    assert (workspace / "report.json").is_file()
    assert (workspace / "report.md").is_file()
