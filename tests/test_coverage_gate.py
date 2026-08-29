import json
from pathlib import Path

from scripts.coverage_gate import check_coverage, coverage_percentages


def _write_coverage(
    path: Path,
    *,
    statement: float,
    branches: int,
    covered_branches: int,
) -> None:
    path.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_covered": statement,
                    "num_branches": branches,
                    "covered_branches": covered_branches,
                }
            }
        ),
        encoding="utf-8",
    )


def test_coverage_gate_accepts_release_floors(tmp_path: Path):
    coverage = tmp_path / "coverage.json"
    _write_coverage(coverage, statement=85.0, branches=100, covered_branches=75)
    assert coverage_percentages(coverage) == (85.0, 75.0)
    assert check_coverage(coverage) == []


def test_coverage_gate_rejects_statement_regression(tmp_path: Path):
    coverage = tmp_path / "coverage.json"
    _write_coverage(coverage, statement=84.99, branches=100, covered_branches=80)
    errors = check_coverage(coverage)
    assert any("statement coverage" in error for error in errors)


def test_coverage_gate_rejects_branch_regression(tmp_path: Path):
    coverage = tmp_path / "coverage.json"
    _write_coverage(coverage, statement=90.0, branches=100, covered_branches=74)
    errors = check_coverage(coverage)
    assert any("branch coverage" in error for error in errors)


def test_coverage_gate_fails_closed_on_malformed_or_inconsistent_input(tmp_path: Path):
    malformed = tmp_path / "malformed.json"
    malformed.write_text("not-json", encoding="utf-8")
    assert check_coverage(malformed)

    inconsistent = tmp_path / "inconsistent.json"
    _write_coverage(inconsistent, statement=90.0, branches=10, covered_branches=11)
    assert any("inconsistent" in error for error in check_coverage(inconsistent))
