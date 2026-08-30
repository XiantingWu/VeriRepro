from __future__ import annotations

import shutil
from pathlib import Path

from scripts.release_checks.public_contract_surface import (
    PUBLIC_CONTRACT_FILES,
    check_public_contract_surface,
)

ROOT = Path(__file__).parents[1]


def _contract_copy(tmp_path: Path) -> Path:
    for relative in PUBLIC_CONTRACT_FILES:
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return tmp_path


def test_public_contract_accepts_current_architecture() -> None:
    errors: list[str] = []

    check_public_contract_surface(ROOT, errors)

    assert errors == []


def test_public_contract_rejects_review_only_pr_claim(tmp_path: Path) -> None:
    root = _contract_copy(tmp_path)
    path = root / "CONTRIBUTING.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nExternal/fork pull requests are review-only.\n",
        encoding="utf-8",
    )
    errors: list[str] = []

    check_public_contract_surface(root, errors)

    assert any("review-only" in error for error in errors)


def test_public_contract_rejects_self_hosted_certification_claim(tmp_path: Path) -> None:
    root = _contract_copy(tmp_path)
    path = root / "docs/TRUST_MODEL.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nThe exact-head self-hosted certification is authoritative.\n",
        encoding="utf-8",
    )
    errors: list[str] = []

    check_public_contract_surface(root, errors)

    assert any("self-hosted certification" in error for error in errors)


def test_public_contract_rejects_automatic_writeback_claim(tmp_path: Path) -> None:
    root = _contract_copy(tmp_path)
    path = root / "docs/PUBLISHING.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nA separate writeback job promotes the files.\n",
        encoding="utf-8",
    )
    errors: list[str] = []

    check_public_contract_surface(root, errors)

    assert any("writeback" in error for error in errors)


def test_public_contract_rejects_missing_github_hosted_pr_ci_claim(tmp_path: Path) -> None:
    root = _contract_copy(tmp_path)
    path = root / "CONTRIBUTING.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("GitHub-hosted PR CI", "PR CI"),
        encoding="utf-8",
    )
    errors: list[str] = []

    check_public_contract_surface(root, errors)

    assert any("GitHub-hosted PR CI" in error for error in errors)
