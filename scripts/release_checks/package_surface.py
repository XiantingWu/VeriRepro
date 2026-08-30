from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from .common import BASE_REQUIRED_FILES, is_at_least, version_tuple

CANONICAL_REPOSITORY = "https://github.com/XiantingWu/VeriRepro"
EXPECTED_REQUIRES_PYTHON = ">=3.11,<3.14"
EXPECTED_PROJECT_URLS = {
    "Homepage": CANONICAL_REPOSITORY,
    "Repository": CANONICAL_REPOSITORY,
    "Issues": f"{CANONICAL_REPOSITORY}/issues",
    "Documentation": f"{CANONICAL_REPOSITORY}/tree/main/docs",
    "Changelog": f"{CANONICAL_REPOSITORY}/blob/main/CHANGELOG.md",
    "Security": f"{CANONICAL_REPOSITORY}/security",
}


def check_required_files(root: Path, errors: list[str]) -> None:
    for relative in BASE_REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"missing required public-release file: {relative}")


def load_pyproject(root: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        payload = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"could not parse pyproject.toml: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("pyproject.toml must contain a TOML object")
        return None
    return payload


def check_package_surface(
    root: Path,
    pyproject: dict[str, Any],
    errors: list[str],
) -> str:
    build_system = pyproject.get("build-system") or {}
    build_requires = [str(item) for item in build_system.get("requires") or []]
    if not any(item.startswith("hatchling>=1.27") for item in build_requires):
        errors.append("build-system must require hatchling>=1.27 for PEP 639 license metadata")

    project = pyproject.get("project") or {}
    version = str(project.get("version") or "")
    if version_tuple(version) is None:
        errors.append("project.version must be a stable MAJOR.MINOR.PATCH release version")
    if project.get("name") != "verirepro":
        errors.append("project.name must be 'verirepro'")
    if project.get("requires-python") != EXPECTED_REQUIRES_PYTHON:
        errors.append(
            "project.requires-python must match the certified Python support range "
            f"{EXPECTED_REQUIRES_PYTHON!r}"
        )
    if project.get("license") != "Apache-2.0":
        errors.append("project.license must be Apache-2.0")
    if "LICENSE" not in (project.get("license-files") or []):
        errors.append("project.license-files must include LICENSE")

    classifiers = [str(item) for item in project.get("classifiers") or []]
    if any(item.startswith("License ::") for item in classifiers):
        errors.append(
            "PEP 639 license expression must not be combined with deprecated License :: classifiers"
        )
    if "Typing :: Typed" not in classifiers:
        errors.append("typed public package must declare the 'Typing :: Typed' classifier")
    for python_minor in ("3.11", "3.12", "3.13"):
        classifier = f"Programming Language :: Python :: {python_minor}"
        if classifier not in classifiers:
            errors.append(f"certified Python support must declare classifier {classifier!r}")

    urls = project.get("urls") or {}
    if not isinstance(urls, dict):
        errors.append("project.urls must be a mapping")
    else:
        for label, expected in EXPECTED_PROJECT_URLS.items():
            if urls.get(label) != expected:
                errors.append(
                    f"project URL {label!r} must use canonical repository surface {expected!r}"
                )

    optional = project.get("optional-dependencies") or {}
    dev_dependencies = [str(item).lower() for item in optional.get("dev") or []]
    for required in (
        "build",
        "coverage",
        "mypy",
        "pytest",
        "pytest-cov",
        "ruff",
        "twine",
    ):
        if not any(
            item == required
            or item.startswith(required + "[")
            or item.startswith(required + ">")
            or item.startswith(required + "=")
            for item in dev_dependencies
        ):
            errors.append(f"dev dependencies must include {required}")

    scripts = project.get("scripts") or {}
    if scripts.get("verirepro") != "verirepro.cli:main":
        errors.append("preferred verirepro console script must use the public verirepro namespace")
    if scripts.get("reproagent") != "reproagent.cli:main":
        errors.append("legacy reproagent console script alias is missing")
    if is_at_least(version, (0, 7, 0)):
        if scripts.get("verirepro-reprobench") != "reproagent.reprobench_adapter:main":
            errors.append("0.7+ release must expose the verirepro-reprobench CLI")
        if scripts.get("verirepro-reprobench-summary") != "reproagent.reprobench_summary:main":
            errors.append("0.7+ release must expose the verirepro-reprobench-summary CLI")

    targets = (((pyproject.get("tool") or {}).get("hatch") or {}).get("build") or {}).get(
        "targets"
    ) or {}
    wheel_packages = (targets.get("wheel") or {}).get("packages") or []
    for package_path in ("src/verirepro", "src/reproagent"):
        if package_path not in wheel_packages:
            errors.append(f"wheel packages must include {package_path}")

    mypy = (pyproject.get("tool") or {}).get("mypy") or {}
    if mypy.get("disallow_untyped_defs") is not True:
        errors.append("public/core mypy gate must disallow untyped definitions")
    mypy_files = {str(item) for item in mypy.get("files") or []}
    required_mypy_paths = (
        ("src/verirepro", "src/reproagent")
        if "src/reproagent" in mypy_files
        else (
            "src/verirepro",
            "src/reproagent/pipeline_policy.py",
            "src/reproagent/pipeline_execution.py",
            "src/reproagent/pipeline_verification.py",
            "src/reproagent/pipeline_reporting.py",
        )
    )
    for required_path in required_mypy_paths:
        if required_path not in mypy_files:
            errors.append(f"mypy gate must cover {required_path}")

    _check_package_version(root, version, errors)
    _check_public_namespace(root, errors)
    _check_public_documents(root, version, errors)
    return version


def _check_package_version(root: Path, version: str, errors: list[str]) -> None:
    init_path = root / "src/reproagent/__init__.py"
    if not init_path.is_file():
        return
    init_text = init_path.read_text(encoding="utf-8")
    match = re.search(
        r'^__version__\s*=\s*["\']([^"\']+)["\']',
        init_text,
        flags=re.MULTILINE,
    )
    if not match:
        errors.append("could not locate reproagent.__version__")
    elif match.group(1) != version:
        errors.append(f"version mismatch: package={match.group(1)} pyproject={version}")


def _check_public_namespace(root: Path, errors: list[str]) -> None:
    public_init_path = root / "src/verirepro/__init__.py"
    if not public_init_path.is_file():
        return
    public_init = public_init_path.read_text(encoding="utf-8")
    if "from reproagent import __version__" not in public_init:
        errors.append("public verirepro namespace must expose the canonical package version")
    if (
        "from reproagent import ReproductionPlan, build_reproduction_plan, reproduce"
        not in public_init
    ):
        errors.append("public verirepro namespace must expose the stable public API")


def _check_public_documents(root: Path, version: str, errors: list[str]) -> None:
    citation_path = root / "CITATION.cff"
    if citation_path.is_file():
        citation = citation_path.read_text(encoding="utf-8")
        if 'title: "VeriRepro:' not in citation:
            errors.append("CITATION.cff must use the public VeriRepro title")
        if f"version: {version}" not in citation:
            errors.append("CITATION.cff version must match pyproject version")
        if f'repository-code: "{CANONICAL_REPOSITORY}"' not in citation:
            errors.append("CITATION.cff must use the canonical repository-code URL")
        if f'url: "{CANONICAL_REPOSITORY}"' not in citation:
            errors.append("CITATION.cff must use the canonical repository URL")

    changelog_path = root / "CHANGELOG.md"
    if changelog_path.is_file():
        changelog = changelog_path.read_text(encoding="utf-8")
        if f"## {version}" not in changelog:
            errors.append("CHANGELOG must contain an entry for the release version")

    readme_path = root / "README.md"
    if not readme_path.is_file():
        return
    readme = readme_path.read_text(encoding="utf-8")
    if not readme.startswith("# VeriRepro"):
        errors.append("README must start with the public VeriRepro brand")
    if "PASS / FAIL / PARTIAL" not in readme and "PASS**" not in readme:
        errors.append("README must document verdict semantics")
    if "verirepro.yaml" not in readme:
        errors.append("README must document the preferred verirepro.yaml manifest name")
    if "run_real_paper_smoke.py" not in readme:
        errors.append("README must document the bounded real-paper discovery smoke")
    if "import verirepro" not in readme:
        errors.append("README must document the public Python import namespace")
    if f"git clone {CANONICAL_REPOSITORY}.git" not in readme:
        errors.append("README must clone the canonical standalone repository")
    if is_at_least(version, (0, 7, 0)) and "verirepro-reprobench" not in readme:
        errors.append("0.7+ README must document the ReproBench CLI")
