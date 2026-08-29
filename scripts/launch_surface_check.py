from __future__ import annotations

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

    issue_config = _read(root, ".github/ISSUE_TEMPLATE/config.yml", errors)
    if issue_config:
        if SECURITY_ADVISORY not in issue_config:
            errors.append(
                "issue template security contact must use the standalone private-advisory URL"
            )
        if "github.com/findwoods/Papers" in issue_config:
            errors.append(
                "issue template must not route public security reports to the private Papers incubator"
            )

    citation = _read(root, "CITATION.cff", errors)
    if citation:
        if f'repository-code: "{REPOSITORY}"' not in citation:
            errors.append("CITATION.cff must identify the canonical standalone repository")
        if f'url: "{REPOSITORY}"' not in citation:
            errors.append("CITATION.cff must expose the canonical standalone URL")

    readme = _read(root, "README.md", errors)
    if readme and "private `Papers/Repository1-ReproAgent/` incubator" in readme:
        errors.append(
            "README public status must not present the standalone tree as a private incubator"
        )

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
    if dependabot_path.is_file():
        dependabot = dependabot_path.read_text(encoding="utf-8")
        if 'package-ecosystem: "pip"' not in dependabot:
            errors.append("Dependabot must monitor Python package dependencies")
        if 'package-ecosystem: "github-actions"' not in dependabot:
            errors.append("Dependabot must monitor pinned GitHub Actions dependencies")

    return errors


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
