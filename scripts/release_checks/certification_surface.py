from __future__ import annotations

from pathlib import Path

PRIVATE_MANAGER_POLICY = "certification/public-manager-policy.json"
CANONICAL_PUBLIC_REPOSITORY = "https://github.com/XiantingWu/VeriRepro"
WORKFLOWS_DIR = ".github/workflows"


def check_certification_surface(root: Path, errors: list[str]) -> None:
    """Public certification surface for the Xianting publication repository.

    Xianting certification is GitHub-hosted only and must never depend on,
    reference, or document a private manager policy.
    """
    policy = root / PRIVATE_MANAGER_POLICY
    if policy.exists() or policy.is_symlink():
        errors.append(
            f"public repository must not contain a private manager policy: {PRIVATE_MANAGER_POLICY}"
        )

    identity = root / "docs/CANONICAL_IDENTITY.md"
    if identity.is_file():
        text = identity.read_text(encoding="utf-8", errors="replace")
        if CANONICAL_PUBLIC_REPOSITORY not in text:
            errors.append(
                "docs/CANONICAL_IDENTITY.md must identify the canonical public repository "
                f"{CANONICAL_PUBLIC_REPOSITORY}"
            )
    else:
        errors.append("missing public canonical identity: docs/CANONICAL_IDENTITY.md")

    workflows = root / WORKFLOWS_DIR
    if not workflows.is_dir():
        errors.append(f"missing public workflow directory: {WORKFLOWS_DIR}")
        return
    for workflow in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        text = workflow.read_text(encoding="utf-8", errors="replace")
        if "self-hosted" in text:
            errors.append(f"workflow must not use self-hosted runners: {workflow.name}")
