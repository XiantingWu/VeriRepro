from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from reproagent.release_provenance import release_source_sha256


def _load_checker(project_root: Path):
    script = project_root / "scripts/release_source_check.py"
    spec = importlib.util.spec_from_file_location("release_source_identity_check", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_tree(root: Path) -> Path:
    files = {
        "pyproject.toml": '[project]\nname = "verirepro"\nversion = "0.7.0"\n',
        "scripts/launch_surface_check.py": "pass\n",
        "scripts/release_check.py": "pass\n",
        "scripts/release_source_check.py": "pass\n",
        "scripts/record_release_evidence.py": "pass\n",
        "scripts/run_real_paper_smoke.py": "pass\n",
        "scripts/stamp_release_measurement.py": "pass\n",
        "scripts/run_reprobench_seed.py": "pass\n",
        ".github/workflows/ci.yml": "name: CI\n",
        ".github/workflows/publish.yml": "name: Publish\n",
        "src/reproagent/a.py": "VALUE = 1\n",
        "src/verirepro/b.py": "VALUE = 2\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _identity(run_id: str = "12345", head_sha: str = "a" * 40) -> dict[str, str]:
    return {
        "workflow": "VeriRepro validation",
        "github_actions_run_id": run_id,
        "head_sha": head_sha,
    }


def _write_evidence(
    root: Path,
    *,
    source_digest: str,
    discovery_identity: dict[str, str] | None = None,
    planning_identity: dict[str, str] | None = None,
    reprobench_identity: dict[str, str] | None = None,
) -> None:
    discovery_identity = discovery_identity or _identity()
    planning_identity = planning_identity or _identity()
    reprobench_identity = reprobench_identity or _identity()

    front_dir = root / "benchmarks"
    front_dir.mkdir(parents=True, exist_ok=True)
    for name, identity in (
        ("real-paper-smoke-results-0.7.0.json", discovery_identity),
        ("environment-planning-results-0.7.0.json", planning_identity),
    ):
        (front_dir / name).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "release": "0.7.0",
                    "measurement_provenance": identity,
                    "provenance": {
                        "github_actions_run_id": identity["github_actions_run_id"],
                        "head_sha": identity["head_sha"],
                    },
                }
            ),
            encoding="utf-8",
        )

    manifest = root / "benchmarks/reprobench-results-0.7.0/manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "release": "0.7.0",
                "source_tree_sha256": source_digest,
                "provenance": reprobench_identity,
            }
        ),
        encoding="utf-8",
    )


def test_release_source_checker_accepts_one_exact_trusted_identity(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[1]
    checker = _load_checker(project_root)
    root = _release_tree(tmp_path / "release")
    digest = release_source_sha256(root)
    _write_evidence(root, source_digest=digest)

    assert checker.check_release_source(root) == []


def test_release_source_checker_rejects_mixed_front_half_runs(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[1]
    checker = _load_checker(project_root)
    root = _release_tree(tmp_path / "release")
    digest = release_source_sha256(root)
    _write_evidence(
        root,
        source_digest=digest,
        planning_identity=_identity(run_id="12346"),
    )

    errors = checker.check_release_source(root)
    assert any("same trusted run/head" in item for item in errors)


def test_release_source_checker_rejects_reprobench_from_other_head(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[1]
    checker = _load_checker(project_root)
    root = _release_tree(tmp_path / "release")
    digest = release_source_sha256(root)
    _write_evidence(
        root,
        source_digest=digest,
        reprobench_identity=_identity(head_sha="b" * 40),
    )

    errors = checker.check_release_source(root)
    assert any("front-half and ReproBench evidence" in item for item in errors)


def test_release_source_checker_rejects_promotion_relabel(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[1]
    checker = _load_checker(project_root)
    root = _release_tree(tmp_path / "release")
    digest = release_source_sha256(root)
    _write_evidence(root, source_digest=digest)

    discovery = root / "benchmarks/real-paper-smoke-results-0.7.0.json"
    payload = json.loads(discovery.read_text(encoding="utf-8"))
    payload["provenance"]["github_actions_run_id"] = "99999"
    discovery.write_text(json.dumps(payload), encoding="utf-8")

    errors = checker.check_release_source(root)
    assert any("promotion provenance must match" in item for item in errors)
