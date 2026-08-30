from __future__ import annotations

import re
from pathlib import Path

PUBLIC_CONTRACT_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "SUPPORT.md",
    "ROADMAP.md",
    "docs/TRUST_MODEL.md",
    "docs/ARCHITECTURE.md",
    "docs/PUBLISHING.md",
    "docs/PUBLIC_RELEASE_CHECKLIST.md",
)

_REQUIRED_FRAGMENTS: dict[str, tuple[str, ...]] = {
    "README.md": (
        "GitHub-hosted PR CI",
        "manual GitHub-hosted validation",
        "explicit evidence-only PR",
    ),
    "CONTRIBUTING.md": (
        "GitHub-hosted PR CI",
        "ordinary PR CI is quality/compatibility CI",
        "validation is not PR-triggered",
        "explicit evidence-only PR",
    ),
    "SECURITY.md": (
        "GitHub-hosted ephemeral PR CI",
        "read-only",
        "no repository secrets",
        "no self-hosted",
        "no pull_request_target",
        "ci.yml is the canonical public PR/main CI",
        "validation.yml is manual GitHub-hosted certification",
        "publish.yml is GitHub-hosted OIDC delivery",
        "Credentialed model integrations are outside ordinary fork PR CI",
    ),
    "SUPPORT.md": (
        "GitHub-hosted secret-free CI",
        "do not receive certification authority",
        "manual GitHub-hosted validation workflow",
    ),
    "ROADMAP.md": (
        "external/fork pull requests run only on GitHub-hosted ephemeral runners",
        "broaden adversarial PR CI resource-boundary tests",
    ),
    "docs/TRUST_MODEL.md": (
        "GitHub-hosted CI is the sole automated CI authority",
        "GitHub-hosted validation is the certification authority",
        "GitHub-hosted publish is the delivery authority",
        "Self-hosted execution authority: none",
        "PR CI success != release certification",
        "explicit evidence-only PR",
    ),
    "docs/ARCHITECTURE.md": (
        "GitHub-hosted fork-PR isolation",
        "secret-free",
        "no self-hosted",
        "no pull_request_target",
        "explicit evidence-only PR",
    ),
    "docs/PUBLISHING.md": (
        "External/fork PRs run public GitHub-hosted CI",
        "explicit evidence-only PR",
        "release tag",
        "cryptographic",
        "GitHub-hosted validation",
    ),
    "docs/PUBLIC_RELEASE_CHECKLIST.md": (
        "timeouts",
        "concurrency",
        "release tag checkout",
        "cryptographic tag verification",
        "main PR rule",
        "strict required checks",
        "conversation resolution",
        "fresh certification",
        "fresh evidence",
    ),
}

_FORBIDDEN_FRAGMENTS = (
    "external/fork pull requests are review-only",
    "external pull requests are review-only",
    "no ordinary pull_request workflow",
    "the repository has no ordinary pull_request",
    "trusted integration/** lane",
    "exact-head self-hosted certification",
    "self-hosted certification authority",
    "the one hosted-runner exception",
    "the project deliberately does not depend on GitHub-hosted CI",
    "does not depend on GitHub-hosted CI",
    "separate writeback job",
    "separate minimal writeback job",
    "automatic writeback job",
    "legacy hosted ci.yml",
    "review-only contribution boundary",
    "trusted integration infrastructure",
)


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", "").casefold()).strip()


def check_public_contract_surface(root: Path, errors: list[str]) -> None:
    """Fail closed when public docs disagree with the current release architecture."""

    root = Path(root).resolve()
    documents: dict[str, str] = {}
    for relative in PUBLIC_CONTRACT_FILES:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            errors.append(f"missing safe public contract document: {relative}")
            continue
        try:
            documents[relative] = _normalized(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"could not read public contract document {relative}: {exc}")

    for relative, fragments in _REQUIRED_FRAGMENTS.items():
        text = documents.get(relative, "")
        for fragment in fragments:
            if _normalized(fragment) not in text:
                errors.append(f"{relative} is missing current public contract: {fragment!r}")

    for relative, text in documents.items():
        for fragment in _FORBIDDEN_FRAGMENTS:
            if _normalized(fragment) in text:
                errors.append(f"{relative} contains retired public contract: {fragment!r}")
