from __future__ import annotations

import shutil
from pathlib import Path

from scripts.launch_surface_check import REPOSITORY, check_launch_surface

ROOT = Path(__file__).resolve().parents[1]
_REQUIRED = (
    "pyproject.toml",
    ".github/ISSUE_TEMPLATE/config.yml",
    "CITATION.cff",
    "README.md",
)
_PUBLIC_DOCS = (
    "README.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "ROADMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/DATASETS.md",
    "docs/ENVIRONMENT.md",
    "docs/ENVIRONMENT_MANAGERS.md",
    "docs/GETTING_STARTED.md",
    "docs/GPU.md",
    "docs/LITELLM.md",
    "docs/MODEL_ARTIFACTS.md",
    "docs/OUTPUTS.md",
    "docs/PUBLISHING.md",
    "docs/REAL_PAPER_SMOKE.md",
    "docs/REPROBENCH.md",
    "docs/SCHEMAS.md",
    "docs/TRUST_MODEL.md",
)
_FORBIDDEN_PUBLIC_PHRASES = (
    "private Papers incubator",
    "private-incubator",
    "Papers/Repository1-ReproAgent",
    "Repository1-ReproAgent/",
    "Repository2-ReproBench",
    "[self-hosted, macOS, ARM64, experiments]",
    "future standalone",
    "ReproAgent v0.3",
    "current 0.7 release candidate",
    "current 0.7 incubator",
)


# This contract is part of the final exact-head standalone public-release gate.
def _surface_copy(tmp_path: Path) -> Path:
    for relative in _REQUIRED:
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return tmp_path


def test_current_public_launch_surface_is_complete() -> None:
    assert check_launch_surface(ROOT) == []


def test_public_docs_are_standalone_facing() -> None:
    for relative in _PUBLIC_DOCS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for phrase in _FORBIDDEN_PUBLIC_PHRASES:
            assert phrase not in text, f"{relative} leaks pre-public/incubator language: {phrase}"

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/PUBLIC_RELEASE_CHECKLIST.md" not in readme
    assert "docs/PUBLIC_SURFACE_AUDIT_0.8.0.md" not in readme
    assert "docs/LAUNCH_READINESS_0.8.0.md" not in readme
    assert "../ops/export_verirepro.py" not in readme


def test_launch_surface_rejects_incubator_project_urls(tmp_path: Path) -> None:
    root = _surface_copy(tmp_path)
    path = root / "pyproject.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            REPOSITORY, "https://github.com/private-incubator/Papers"
        ),
        encoding="utf-8",
    )

    errors = check_launch_surface(root)

    assert any("canonical standalone URL" in error for error in errors)


def test_launch_surface_rejects_incubator_security_route(tmp_path: Path) -> None:
    root = _surface_copy(tmp_path)
    path = root / ".github/ISSUE_TEMPLATE/config.yml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "https://github.com/XiantingWu/VeriRepro/security/advisories/new",
            "https://github.com/private-incubator/Papers/security",
        ),
        encoding="utf-8",
    )

    errors = check_launch_surface(root)

    assert any("private-advisory" in error for error in errors)
    assert any("non-canonical GitHub repository" in error for error in errors)
