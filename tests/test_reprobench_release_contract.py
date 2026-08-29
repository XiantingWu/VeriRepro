from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


def test_reprobench_public_release_surface_is_present_and_independent() -> None:
    root = Path(__file__).parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]
    assert scripts["verirepro-reprobench"] == "reproagent.reprobench_adapter:main"
    assert scripts["verirepro-reprobench-summary"] == "reproagent.reprobench_summary:main"

    required = (
        root / "docs/REPROBENCH.md",
        root / "benchmarks/reprobench-seed-suite.json",
        root / "scripts/run_reprobench_seed.py",
        root / "src/reproagent/reprobench_adapter.py",
        root / "src/reproagent/reprobench_summary.py",
        root / "src/verirepro/reprobench.py",
    )
    for path in required:
        assert path.is_file(), f"missing ReproBench public-release file: {path.relative_to(root)}"

    implementation = (root / "src/reproagent/reprobench_adapter.py").read_text(encoding="utf-8")
    summary = (root / "src/reproagent/reprobench_summary.py").read_text(encoding="utf-8")
    public_wrapper = (root / "src/verirepro/reprobench.py").read_text(encoding="utf-8")
    docs = (root / "docs/REPROBENCH.md").read_text(encoding="utf-8")

    forbidden = (
        "Repository2-ReproBench",
        "from reprobench",
        "import reprobench",
        "sys.path.append",
        "sys.path.insert",
    )
    for fragment in forbidden:
        assert fragment not in implementation
        assert fragment not in summary
        assert fragment not in public_wrapper

    assert "JSON/process boundary" in docs
    assert "untrusted" in docs
    assert "intervention" in docs
    assert "local paper paths" in docs
    assert "verirepro-reprobench-summary" in docs


def test_release_seed_suite_is_bounded_real_and_commit_pinned() -> None:
    root = Path(__file__).parents[1]
    suite = json.loads((root / "benchmarks/reprobench-seed-suite.json").read_text(encoding="utf-8"))
    cases = suite["cases"]
    assert 2 <= len(cases) <= 10
    assert len({case["task"] for case in cases}) == len(cases)
    scientific_successes = 0
    for case in cases:
        assert re.fullmatch(r"[0-9a-f]{40}", case["repository_ref"])
        assert case["use_llm"] is False
        assert case["allow_network"] is False
        assert case["trust_repository_contract"] is False
        assert case["release_gate"]["environment_build_status"] == "passed"
        assert case["release_gate"]["experiment_execution_status"] == "passed"
        if case.get("scientific_artifacts"):
            scientific_successes += 1
            assert case["release_gate"]["outcome"] == "success"
            assert case["release_gate"]["failure_taxonomy"] == []
            assert case["release_gate"]["intervention_count"] == 4
            for artifact in case["scientific_artifacts"]:
                assert artifact["kind"] in {"table", "figure", "file"}
                assert artifact["reference"]
                assert artifact["reproduced"]
        else:
            assert case["release_gate"]["intervention_count"] == 3
    assert scientific_successes >= 1


def test_release_check_07_requires_version_matched_front_half_and_reprobench() -> None:
    root = Path(__file__).parents[1]
    surface = (root / "scripts/release_checks/benchmark_surface.py").read_text(encoding="utf-8")
    common = (root / "scripts/release_checks/common.py").read_text(encoding="utf-8")
    assert "def front_half_evidence_version" in surface
    assert "return version" in surface
    assert "real-paper-smoke-results-{evidence_version}.json" in surface
    assert "environment-planning-results-{evidence_version}.json" in surface
    assert "_check_reprobench_release_evidence" in surface
    assert "reprobench-results-{version}" in surface
    assert "suite_sha256" in surface
    assert "result_sha256" in surface
    assert "summary_sha256" in surface
    assert "github_actions_run_id" in surface
    assert '"api_key"' in common
    assert '"workspace"' in common
