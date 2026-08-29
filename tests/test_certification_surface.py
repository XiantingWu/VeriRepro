from __future__ import annotations

from pathlib import Path

from scripts.release_checks.certification_surface import (
    CANONICAL_PUBLIC_REPOSITORY,
    PRIVATE_MANAGER_POLICY,
    check_certification_surface,
)

ROOT = Path(__file__).resolve().parents[1]


def test_current_public_certification_surface_is_clean() -> None:
    errors: list[str] = []
    check_certification_surface(ROOT, errors)
    assert not any("private manager" in item for item in errors)
    assert not any("self-hosted" in item for item in errors)


def test_certification_surface_rejects_private_manager_policy(tmp_path: Path) -> None:
    root = tmp_path
    (root / "docs").mkdir(parents=True)
    (root / "docs/CANONICAL_IDENTITY.md").write_text(
        f"Canonical public repository:\n{CANONICAL_PUBLIC_REPOSITORY}\n",
        encoding="utf-8",
    )
    (root / ".github/workflows").mkdir(parents=True)
    (root / ".github/workflows/ci.yml").write_text(
        "name: CI\nruns-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    policy = root / PRIVATE_MANAGER_POLICY
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text("{}", encoding="utf-8")

    errors: list[str] = []
    check_certification_surface(root, errors)
    assert any(PRIVATE_MANAGER_POLICY in item for item in errors)


def test_certification_surface_rejects_self_hosted_workflow(tmp_path: Path) -> None:
    root = tmp_path
    (root / "docs").mkdir(parents=True)
    (root / "docs/CANONICAL_IDENTITY.md").write_text(
        f"Canonical public repository:\n{CANONICAL_PUBLIC_REPOSITORY}\n",
        encoding="utf-8",
    )
    (root / ".github/workflows").mkdir(parents=True)
    (root / ".github/workflows/ci.yml").write_text(
        "name: CI\nruns-on: self-hosted\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check_certification_surface(root, errors)
    assert any("self-hosted" in item for item in errors)


def test_certification_surface_rejects_non_canonical_identity(tmp_path: Path) -> None:
    root = tmp_path
    (root / "docs").mkdir(parents=True)
    (root / "docs/CANONICAL_IDENTITY.md").write_text(
        "Canonical public repository:\nhttps://github.com/example/Other\n",
        encoding="utf-8",
    )
    (root / ".github/workflows").mkdir(parents=True)
    (root / ".github/workflows/ci.yml").write_text(
        "name: CI\nruns-on: ubuntu-latest\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check_certification_surface(root, errors)
    assert any("CANONICAL_IDENTITY" in item for item in errors)


def test_certification_surface_requires_workflow_directory(tmp_path: Path) -> None:
    root = tmp_path
    (root / "docs").mkdir(parents=True)
    (root / "docs/CANONICAL_IDENTITY.md").write_text(
        f"Canonical public repository:\n{CANONICAL_PUBLIC_REPOSITORY}\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    check_certification_surface(root, errors)
    assert any(".github/workflows" in item for item in errors)
