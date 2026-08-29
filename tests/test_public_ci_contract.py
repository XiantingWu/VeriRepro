from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
_PIN = re.compile(r"@[0-9a-f]{40}(?:\s|$)")
_EXECUTABLE = ("ci.yml", "validation.yml", "publish.yml")


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _all_workflow_texts() -> list[tuple[str, str]]:
    return [
        (path.name, path.read_text(encoding="utf-8"))
        for path in (*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml"))
    ]


def test_ci_exists_and_runs_on_pull_request_and_push_main() -> None:
    ci = _workflow("ci.yml")
    assert "pull_request:" in ci
    assert "push:" in ci
    assert "branches: [main]" in ci or "branches: ['main']" in ci


def test_all_executable_workflow_jobs_use_github_hosted_runners() -> None:
    for name, text in _all_workflow_texts():
        assert "runs-on: self-hosted" not in text, name
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("runs-on:"):
                assert "ubuntu-latest" in stripped, f"{name}: {stripped}"


def test_no_private_runner_labels_or_groups() -> None:
    for name, text in _all_workflow_texts():
        assert "runner-group" not in text, name
        assert "experiments" not in text, name
        assert "repo-" not in text, name


def test_no_pull_request_target_contributor_execution() -> None:
    for name, text in _all_workflow_texts():
        assert "pull_request_target:" not in text, name


def test_pull_request_ci_is_secret_free() -> None:
    ci = _workflow("ci.yml")
    assert "secrets." not in ci


def test_no_workflow_uses_repository_secrets() -> None:
    for name, text in _all_workflow_texts():
        assert "secrets." not in text, name


def test_checkout_never_persists_credentials() -> None:
    for name, text in _all_workflow_texts():
        assert "persist-credentials: false" in text, name


def test_permissions_are_read_only_unless_release_scoped() -> None:
    for name, text in _all_workflow_texts():
        assert "permissions:\n  contents: read" in text, name
        if name == "publish.yml":
            assert "id-token: write" in text
        else:
            assert "id-token: write" not in text, name


def test_third_party_actions_pinned_to_40_char_sha() -> None:
    for name, text in _all_workflow_texts():
        for line in text.splitlines():
            stripped = line.strip()
            if "uses:" in stripped:
                assert _PIN.search(stripped), f"{name}: {stripped}"


def test_validation_is_dispatch_only_and_has_no_writeback() -> None:
    validation = _workflow("validation.yml")
    assert "workflow_dispatch:" in validation
    assert "pull_request:" not in validation
    assert "pull_request_target:" not in validation
    assert "git push" not in validation
    assert "contents: write" not in validation
    assert "actions/upload-artifact@" in validation


def test_publish_is_release_only_with_oidc_trusted_publishing() -> None:
    publish = _workflow("publish.yml")
    assert "release:\n    types: [published]" in publish
    assert "pull_request:" not in publish
    assert "pull_request_target:" not in publish
    assert "environment:\n      name: pypi" in publish
    assert "id-token: write" in publish
    assert "pypa/gh-action-pypi-publish@" in publish
    for forbidden in ("PYPI_API_TOKEN", "password:", "username:"):
        assert forbidden not in publish, forbidden


def test_compatibility_matrix_covers_python_312_and_313() -> None:
    ci = _workflow("ci.yml")
    assert "python-version: '3.11'" in ci
    assert "python-version: '3.12'" in ci
    assert "python-version: '3.13'" in ci