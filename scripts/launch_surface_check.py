from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/XiantingWu/VeriRepro"
SECURITY_ADVISORY = f"{REPOSITORY}/security/advisories/new"
EXPECTED_URLS = {
    "Homepage": REPOSITORY,
    "Repository": REPOSITORY,
    "Issues": f"{REPOSITORY}/issues",
    "Documentation": f"{REPOSITORY}/tree/main/docs",
    "Changelog": f"{REPOSITORY}/blob/main/CHANGELOG.md",
    "Security": f"{REPOSITORY}/security",
}
PUBLIC_IDENTITY_FILES = (
    "README.md",
    "docs/CANONICAL_IDENTITY.md",
    "docs/GETTING_STARTED.md",
    "docs/PUBLISHING.md",
    "docs/PUBLIC_RELEASE_CHECKLIST.md",
    "CITATION.cff",
    ".github/ISSUE_TEMPLATE/config.yml",
)
_GITHUB_URL = re.compile(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def _read(root: Path, relative: str, errors: list[str]) -> str:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        errors.append(f"missing safe public-launch file: {relative}")
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"could not read {relative}: {exc}")
        return ""


def _non_canonical_github_urls(text: str) -> list[str]:
    return [url for url in _GITHUB_URL.findall(text) if not url.startswith(REPOSITORY)]


def check_launch_surface(root: Path = ROOT) -> list[str]:
    root = Path(root).resolve()
    errors: list[str] = []

    pyproject_text = _read(root, "pyproject.toml", errors)
    if pyproject_text:
        try:
            project = tomllib.loads(pyproject_text)["project"]
        except (tomllib.TOMLDecodeError, KeyError) as exc:
            errors.append(f"could not parse pyproject project metadata: {exc}")
        else:
            urls = project.get("urls")
            if not isinstance(urls, dict):
                errors.append("pyproject.toml must define [project.urls]")
            else:
                for label, expected in EXPECTED_URLS.items():
                    if urls.get(label) != expected:
                        errors.append(
                            f"project URL {label!r} must be the canonical standalone URL {expected!r}"
                        )

    public_identity: dict[str, str] = {}
    for relative in PUBLIC_IDENTITY_FILES:
        text = _read(root, relative, errors)
        public_identity[relative] = text
        for url in _non_canonical_github_urls(text):
            errors.append(
                f"public identity file must not reference a non-canonical GitHub repository: "
                f"{relative}: {url}"
            )

    issue_config = public_identity[".github/ISSUE_TEMPLATE/config.yml"]
    if issue_config:
        if SECURITY_ADVISORY not in issue_config:
            errors.append(
                "issue template security contact must use the canonical private-advisory URL"
            )

    citation = public_identity["CITATION.cff"]
    if citation:
        if f'repository-code: "{REPOSITORY}"' not in citation:
            errors.append("CITATION.cff must identify the canonical standalone repository")
        if f'url: "{REPOSITORY}"' not in citation:
            errors.append("CITATION.cff must expose the canonical standalone URL")

    readme = public_identity["README.md"]
    if readme:
        if "private `Papers/Repository1-ReproAgent/` incubator" in readme:
            errors.append(
                "README public status must not present the standalone tree as a private incubator"
            )
        if f"git clone {REPOSITORY}.git" not in readme:
            errors.append("README quick start must clone the canonical standalone repository")

    canonical_identity = public_identity["docs/CANONICAL_IDENTITY.md"]
    if canonical_identity:
        if REPOSITORY not in canonical_identity:
            errors.append("canonical identity document must name the authoritative repository")
        if "not canonical VeriRepro release authorities" not in canonical_identity:
            errors.append(
                "canonical identity document must distinguish copies from release authority"
            )

    getting_started = public_identity["docs/GETTING_STARTED.md"]
    if getting_started and f"git clone {REPOSITORY}.git" not in getting_started:
        errors.append("getting-started guide must clone the canonical standalone repository")

    publishing_doc = public_identity["docs/PUBLISHING.md"]
    if publishing_doc:
        if f"{REPOSITORY}" not in publishing_doc:
            errors.append("publishing guide must document the canonical standalone repository")
        if "Trusted Publishing" not in publishing_doc:
            errors.append("publishing guide must document PyPI Trusted Publishing")

    release_checklist = public_identity["docs/PUBLIC_RELEASE_CHECKLIST.md"]
    if release_checklist:
        if (
            "previous source/fingerprint/run are labelled historical after release-relevant hardening"
            not in release_checklist
        ):
            errors.append("release checklist must distinguish historical from current 0.8 evidence")

    publish_path = root / ".github/workflows/publish.yml"
    if publish_path.is_file():
        publish = publish_path.read_text(encoding="utf-8")
        if "if: ${{ github.event.release.prerelease == false }}" not in publish:
            errors.append("PyPI publish job must fail closed for GitHub prereleases")
        if "name: pypi" not in publish or "id-token: write" not in publish:
            errors.append(
                "PyPI publish job must retain the protected pypi environment and OIDC permission"
            )

    dependabot_path = root / ".github/dependabot.yml"
    if not dependabot_path.is_file():
        errors.append("Dependabot policy must be provisioned")
    else:
        dependabot = dependabot_path.read_text(encoding="utf-8")
        _check_dependabot_policy(dependabot, errors)

    return errors


def _check_dependabot_policy(text: str, errors: list[str]) -> None:
    blocks = re.split(r"(?=^  - package-ecosystem:)", text, flags=re.MULTILINE)
    for ecosystem, label in (
        ('package-ecosystem: "pip"', "Python package"),
        ('package-ecosystem: "github-actions"', "GitHub Actions"),
    ):
        block = next((item for item in blocks if ecosystem in item), "")
        if not block:
            errors.append(f"Dependabot must monitor {label} dependencies")
            continue
        if "allow:" not in block:
            errors.append(f"Dependabot {label} policy must explicitly allow routine updates")
        for update_type in ("semver-minor", "semver-patch"):
            if f'"version-update:{update_type}"' not in block:
                errors.append(f"Dependabot {label} policy must allow version-update:{update_type}")
        if re.search(r"(?ms)^\s+ignore:\s*$.*?version-update:semver-major", block):
            errors.append(
                f"Dependabot {label} policy must not wildcard-ignore semver-major updates"
            )


def main() -> int:
    errors = check_launch_surface()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: standalone public launch surface is canonical and fail-closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
