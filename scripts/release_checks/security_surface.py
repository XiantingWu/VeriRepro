from __future__ import annotations

import re
from pathlib import Path

CANONICAL_REPOSITORY = "https://github.com/XiantingWu/VeriRepro"
SECURITY_ADVISORY = f"{CANONICAL_REPOSITORY}/security/advisories/new"
FORK_EXECUTION_BOUNDARY = (
    "Do not execute external fork pull-request code on persistent self-hosted runners"
)


def check_security_surface(root: Path, errors: list[str]) -> None:
    """Validate public security-reporting and contribution trust-boundary declarations."""
    security_path = root / "SECURITY.md"
    issue_config_path = root / ".github/ISSUE_TEMPLATE/config.yml"

    if security_path.is_file():
        security = security_path.read_text(encoding="utf-8")
        required_phrases = (
            "GitHub-only HTTPS repository cloning",
            "double opt-in experiment networking",
            "double opt-in GPU device access",
            "Public pull requests and CI isolation",
            "private vulnerability-reporting flow",
        )
        for phrase in required_phrases:
            if phrase not in security:
                errors.append(f"SECURITY.md must document release trust boundary: {phrase}")
        if FORK_EXECUTION_BOUNDARY not in security:
            errors.append(
                "SECURITY.md must explicitly forbid self-hosted execution of fork PR code"
            )
        if "Papers/Repository1-ReproAgent" in security:
            errors.append("SECURITY.md must not depend on the historical incubator repository")

    if issue_config_path.is_file():
        issue_config = issue_config_path.read_text(encoding="utf-8")
        if SECURITY_ADVISORY not in issue_config:
            errors.append(
                "security issue contact must route to the canonical private advisory flow"
            )
        for url in re.findall(
            r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", issue_config
        ):
            if not url.startswith(CANONICAL_REPOSITORY):
                errors.append(
                    "security issue contact must not route to non-canonical GitHub repositories"
                )
