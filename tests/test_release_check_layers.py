from pathlib import Path

import pytest

from scripts.release_check import check_release_tree
from scripts.release_checks.common import safe_relative_path
from scripts.release_checks.package_surface import check_package_surface
from scripts.release_checks.security_surface import check_security_surface
from scripts.release_checks.workflow_surface import check_workflow_surface


def test_safe_relative_path_rejects_escape_and_absolute_forms():
    for value in ("../secret", "/etc/passwd", "C:/secret", "a//b", "./file"):
        with pytest.raises(ValueError, match="confined relative path"):
            safe_relative_path(value, field="evidence")
    assert safe_relative_path("results/case.json", field="evidence") == Path("results/case.json")


def test_package_surface_rejects_historical_repository_urls(tmp_path: Path):
    (tmp_path / "src/reproagent").mkdir(parents=True)
    (tmp_path / "src/verirepro").mkdir(parents=True)
    (tmp_path / "src/reproagent/__init__.py").write_text(
        '__version__ = "0.8.0"\n', encoding="utf-8"
    )
    (tmp_path / "src/verirepro/__init__.py").write_text(
        "from reproagent import ReproductionPlan, build_reproduction_plan, reproduce\n"
        "from reproagent import __version__\n",
        encoding="utf-8",
    )
    (tmp_path / "CITATION.cff").write_text(
        'title: "VeriRepro: Demo"\nversion: 0.8.0\n', encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text("## 0.8.0\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# VeriRepro\n", encoding="utf-8")
    pyproject = {
        "build-system": {"requires": ["hatchling>=1.27"]},
        "project": {
            "name": "verirepro",
            "version": "0.8.0",
            "license": "Apache-2.0",
            "license-files": ["LICENSE"],
            "classifiers": [],
            "urls": {
                "Homepage": "https://github.com/private-incubator/VeriRepro",
                "Repository": "https://github.com/private-incubator/VeriRepro",
            },
            "optional-dependencies": {
                "dev": [
                    "build>=1.2",
                    "coverage[toml]>=7.6",
                    "pytest>=8",
                    "pytest-cov>=6",
                    "ruff>=0.12",
                    "twine>=6",
                ]
            },
            "scripts": {
                "verirepro": "verirepro.cli:main",
                "reproagent": "reproagent.cli:main",
                "verirepro-reprobench": "reproagent.reprobench_adapter:main",
                "verirepro-reprobench-summary": "reproagent.reprobench_summary:main",
            },
        },
        "tool": {
            "hatch": {
                "build": {"targets": {"wheel": {"packages": ["src/verirepro", "src/reproagent"]}}}
            }
        },
    }
    errors: list[str] = []
    check_package_surface(tmp_path, pyproject, errors)
    assert any("canonical repository surface" in item for item in errors)
    assert any("canonical repository-code" in item for item in errors)


def test_security_surface_requires_private_advisory_and_fork_isolation(tmp_path: Path):
    (tmp_path / ".github/ISSUE_TEMPLATE").mkdir(parents=True)
    (tmp_path / "SECURITY.md").write_text(
        "GitHub-only HTTPS repository cloning\n"
        "double opt-in experiment networking\n"
        "double opt-in GPU device access\n"
        "Public pull requests and CI isolation\n"
        "private vulnerability-reporting flow\n",
        encoding="utf-8",
    )
    (tmp_path / ".github/ISSUE_TEMPLATE/config.yml").write_text(
        "url: https://github.com/private-incubator/Papers/security\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    check_security_surface(tmp_path, errors)
    assert any("self-hosted execution of fork PR code" in item for item in errors)
    assert any("canonical private advisory" in item for item in errors)
    assert any("non-canonical GitHub repositories" in item for item in errors)


def test_security_surface_accepts_canonical_private_advisory_route(tmp_path: Path):
    (tmp_path / ".github/ISSUE_TEMPLATE").mkdir(parents=True)
    (tmp_path / "SECURITY.md").write_text(
        "- GitHub-only HTTPS repository cloning\n"
        "- double opt-in experiment networking\n"
        "- double opt-in GPU device access\n"
        "- Public pull requests and CI isolation\n"
        "- private vulnerability-reporting flow\n"
        "- No self-hosted execution and no `pull_request_target` may be used for contributor code\n",
        encoding="utf-8",
    )
    (tmp_path / ".github/ISSUE_TEMPLATE/config.yml").write_text(
        "contact:\n  link: https://github.com/XiantingWu/VeriRepro/security/advisories/new\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    check_security_surface(tmp_path, errors)
    assert errors == []


def test_security_surface_rejects_historical_incubator_in_security_md(tmp_path: Path):
    (tmp_path / "SECURITY.md").write_text(
        "GitHub-only HTTPS repository cloning\n"
        "double opt-in experiment networking\n"
        "double opt-in GPU device access\n"
        "Public pull requests and CI isolation\n"
        "private vulnerability-reporting flow\n"
        "No self-hosted execution and no `pull_request_target` may be used for contributor code\n"
        "report to Papers/Repository1-ReproAgent instead\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    check_security_surface(tmp_path, errors)
    assert any("historical incubator repository" in item for item in errors)


def _hosted_ci(tmp_path: Path) -> Path:
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: CI\n"
        "on:\n"
        "  pull_request:\n"
        "  push:\n    branches: [main]\n"
        "permissions:\n  contents: read\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@" + "a" * 40 + "\n"
        "        with:\n          persist-credentials: false\n",
        encoding="utf-8",
    )
    return tmp_path


def test_workflow_surface_rejects_self_hosted_runner(tmp_path: Path):
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: CI\n"
        "on:\n  push:\n    branches: [main]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: self-hosted\n"
        "    steps:\n"
        "      - uses: actions/checkout@" + "a" * 40 + "\n"
        "        with:\n          persist-credentials: false\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    check_workflow_surface(tmp_path, errors)
    assert any("self-hosted" in item for item in errors)


def test_workflow_surface_rejects_private_runner_labels_and_groups(tmp_path: Path):
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: CI\n"
        "on:\n  push:\n    branches: [main]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: [ubuntu-latest, group: private, experiments]\n"
        "    steps:\n"
        "      - uses: actions/checkout@" + "a" * 40 + "\n"
        "        with:\n          persist-credentials: false\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    check_workflow_surface(tmp_path, errors)
    assert any("private runner labels or groups" in item for item in errors)


def test_workflow_surface_accepts_hosted_ci(tmp_path: Path):
    root = _hosted_ci(tmp_path)
    errors: list[str] = []
    check_workflow_surface(root, errors)
    assert not any("self-hosted" in item for item in errors)


def test_workflow_surface_rejects_pull_request_target(tmp_path: Path):
    workflow = tmp_path / ".github/workflows/metadata.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: Metadata\n"
        "on:\n  pull_request_target:\n"
        "jobs:\n"
        "  inspect:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@" + "a" * 40 + "\n"
        "        with:\n          persist-credentials: false\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    check_workflow_surface(tmp_path, errors)
    assert any("must not use pull_request_target" in item for item in errors)


def test_workflow_surface_rejects_secrets_in_pull_request_ci(tmp_path: Path):
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: CI\n"
        "on:\n  pull_request:\n"
        "permissions:\n  contents: read\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@" + "a" * 40 + "\n"
        "        with:\n          persist-credentials: false\n"
        '      - run: echo "${{ secrets.PYPI_API_TOKEN }}"\n',
        encoding="utf-8",
    )
    errors: list[str] = []
    check_workflow_surface(tmp_path, errors)
    assert any("secret-free" in item for item in errors)


def test_workflow_surface_requires_checkout_credential_isolation(tmp_path: Path):
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: CI\n"
        "on:\n  push:\n    branches: [main]\n"
        "permissions:\n  contents: read\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@" + "a" * 40 + "\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    check_workflow_surface(tmp_path, errors)
    assert any("persist repository credentials" in item for item in errors)


def test_workflow_surface_requires_action_sha_pins(tmp_path: Path):
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: CI\n"
        "on:\n  push:\n    branches: [main]\n"
        "permissions:\n  contents: read\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n          persist-credentials: false\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    check_workflow_surface(tmp_path, errors)
    assert any("40-character commit SHA" in item for item in errors)


def test_publish_requires_oidc_and_rejects_long_lived_credentials(tmp_path: Path):
    workflow = tmp_path / ".github/workflows/publish.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: Publish\n"
        "on:\n  release:\n    types: [published]\n"
        "jobs:\n"
        "  publish:\n"
        "    runs-on: ubuntu-latest\n"
        "    environment:\n      name: pypi\n"
        "    permissions:\n      id-token: write\n"
        "    steps:\n"
        "      - uses: pypa/gh-action-pypi-publish@" + "a" * 40 + "\n",
        encoding="utf-8",
    )
    errors: list[str] = []
    check_workflow_surface(tmp_path, errors)
    assert not any("self-hosted" in item for item in errors)
    assert not any("long-lived credential" in item for item in errors)


def test_release_tree_aggregator_is_importable_and_fail_closed(tmp_path: Path):
    errors = check_release_tree(tmp_path)
    assert errors
    assert any("missing required public-release file" in item for item in errors)
