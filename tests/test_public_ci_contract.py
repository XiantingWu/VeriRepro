from __future__ import annotations

import re
import shutil
from pathlib import Path

from scripts.release_checks.action_pin import (
    PYPI_PUBLISH_ACTION,
    PYPI_PUBLISH_ACTION_COMMIT_SHA,
    PYPI_PUBLISH_ACTION_IMAGE,
    PYPI_PUBLISH_ACTION_TAG_OBJECT_SHA,
)
from scripts.release_checks.workflow_surface import check_workflow_surface

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


def test_ci_cancels_stale_same_pr_or_branch_runs() -> None:
    ci = _workflow("ci.yml")
    assert "concurrency:" in ci
    assert (
        "group: ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}"
        in ci
    )
    assert "cancel-in-progress: true" in ci


def test_all_public_ci_jobs_have_explicit_timeouts() -> None:
    ci = _workflow("ci.yml")
    assert ci.count("timeout-minutes:") == 3
    assert "timeout-minutes: 45" in ci
    assert ci.count("timeout-minutes: 30") == 2


def test_publish_checks_out_release_tag() -> None:
    publish = _workflow("publish.yml")
    assert "ref: ${{ github.event.release.tag_name }}" in publish


def test_publish_does_not_checkout_target_commitish() -> None:
    publish = _workflow("publish.yml")
    assert "github.event.release.target_commitish" not in publish


def test_publish_requires_cryptographic_tag_verification() -> None:
    publish = _workflow("publish.yml")
    assert "python scripts/verify_release_tag.py" in publish
    assert "--allowed-signers .github/release-signers" in publish
    assert "git verify-tag" in (ROOT / "scripts/verify_release_tag.py").read_text(encoding="utf-8")


def test_publish_rejects_signature_block_only_policy() -> None:
    publish = _workflow("publish.yml")
    assert "grep -Eq" not in publish


def test_publish_uses_dereferenced_pypi_action_commit() -> None:
    publish = _workflow("publish.yml")
    assert f"{PYPI_PUBLISH_ACTION}@{PYPI_PUBLISH_ACTION_COMMIT_SHA}" in publish
    assert f"{PYPI_PUBLISH_ACTION}@{PYPI_PUBLISH_ACTION_TAG_OBJECT_SHA}" not in publish


def test_publish_annotated_tag_object_sha_is_rejected(tmp_path: Path) -> None:
    workflow_dir = tmp_path / ".github/workflows"
    workflow_dir.mkdir(parents=True)
    for path in WORKFLOWS.glob("*.yml"):
        shutil.copyfile(path, workflow_dir / path.name)
    publish_path = workflow_dir / "publish.yml"
    publish = publish_path.read_text(encoding="utf-8")
    publish_path.write_text(
        publish.replace(PYPI_PUBLISH_ACTION_COMMIT_SHA, PYPI_PUBLISH_ACTION_TAG_OBJECT_SHA),
        encoding="utf-8",
    )

    errors: list[str] = []
    check_workflow_surface(tmp_path, errors)

    assert any("tag-object SHA" in item for item in errors)


def test_validation_preflights_exact_pypi_action_runtime_image() -> None:
    validation = _workflow("validation.yml")
    assert "docker manifest inspect" in validation
    assert PYPI_PUBLISH_ACTION_IMAGE in validation
    assert "id-token: write" not in validation


def test_publish_requires_current_canonical_main_head_equality() -> None:
    publish = _workflow("publish.yml")
    assert 'TAG_COMMIT="$(git rev-parse "${GITHUB_REF_NAME}^{commit}")"' in publish
    assert 'MAIN_COMMIT="$(git rev-parse origin/main)"' in publish
    assert 'test "$TAG_COMMIT" = "$MAIN_COMMIT"' in publish


def test_publish_rejects_ancestry_only_without_current_head_gate(tmp_path: Path) -> None:
    workflow_dir = tmp_path / ".github/workflows"
    workflow_dir.mkdir(parents=True)
    for path in WORKFLOWS.glob("*.yml"):
        shutil.copyfile(path, workflow_dir / path.name)
    publish_path = workflow_dir / "publish.yml"
    publish = publish_path.read_text(encoding="utf-8")
    equality_gate = (
        '          MAIN_COMMIT="$(git rev-parse origin/main)"\n'
        '          test "$TAG_COMMIT" = "$MAIN_COMMIT" || {\n'
        "            echo 'Stable release tag must identify the current canonical main head.' >&2\n"
        "            exit 2\n"
        "          }\n"
    )
    publish_path.write_text(publish.replace(equality_gate, ""), encoding="utf-8")

    errors: list[str] = []
    check_workflow_surface(tmp_path, errors)

    assert any("current canonical main head" in item for item in errors)


def test_dependency_review_is_pull_request_only_and_read_only() -> None:
    workflow = _workflow("dependency-review.yml")
    assert "pull_request:" in workflow
    for forbidden in ("push:", "pull_request_target:", "workflow_dispatch:", "secrets."):
        assert forbidden not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "timeout-minutes: 15" in workflow
    assert "actions/dependency-review-action@" in workflow
    assert "fail-on-severity: high" in workflow
