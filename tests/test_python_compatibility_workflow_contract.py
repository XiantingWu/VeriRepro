from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def _ci() -> str:
    return (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_compatibility_lanes_cover_all_advertised_python_minors() -> None:
    ci = _ci()
    for minor in ("3.11", "3.12", "3.13"):
        assert f"python-version: '{minor}'" in ci, minor


def test_compatibility_lanes_run_full_pytest_suite() -> None:
    ci = _ci()
    assert "python -m pytest -q" in ci
    assert ci.count("python -m pytest -q") >= 3


def test_all_lanes_are_github_hosted() -> None:
    ci = _ci()
    assert "runs-on: ubuntu-latest" in ci
    assert "self-hosted" not in ci
    assert ci.count("runs-on: ubuntu-latest") == ci.count("runs-on:")


def test_quality_lane_fails_closed_on_coverage_floors() -> None:
    ci = _ci()
    assert "scripts/coverage_gate.py" in ci
    assert "--min-statement 85" in ci
    assert "--min-branch 75" in ci


def test_quality_lane_runs_release_and_launch_gates() -> None:
    ci = _ci()
    assert "scripts/release_check.py" in ci
    assert "scripts/launch_surface_check.py" in ci
    assert "scripts/history_scan.py" in ci
    assert "python -m twine check dist/*" in ci
    assert "python -m build" in ci


def test_quality_lane_uses_setup_python_actions() -> None:
    ci = _ci()
    assert "actions/setup-python@" in ci