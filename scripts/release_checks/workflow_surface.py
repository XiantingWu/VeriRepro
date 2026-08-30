from __future__ import annotations

import re
from pathlib import Path

from .common import workflow_runs_on_lines, workflow_uses_lines

HOSTED_RUNNERS = ("ubuntu-latest", "macos-latest", "windows-latest")
_PRIVATE_LABEL_MARKERS = (
    "self-hosted",
    "runner-group",
    "group:",
    "experiments",
    "repo-",
)
_PIN = re.compile(r"@[0-9a-f]{40}(?:\s|$)")


def check_workflow_surface(root: Path, errors: list[str]) -> None:
    """Public workflow contract: GitHub-hosted runners only, fork-safe, secret-free.

    The Xianting public repository must never execute workflow jobs on
    maintainer-owned self-hosted runners, private runner labels, or runner
    groups. The only runner authority is GitHub-hosted Actions infrastructure.
    """
    workflows = root / ".github/workflows"
    if not workflows.is_dir():
        errors.append("missing public workflow directory: .github/workflows")
        return

    for path in sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml"))):
        text = path.read_text(encoding="utf-8")
        label = path.relative_to(root).as_posix()
        _check_runner_policy(text, label=label, errors=errors)
        _check_events(text, label=label, errors=errors)
        _check_credentials(text, label=label, errors=errors)
        _check_action_pins(text, label=label, errors=errors)
        _check_permissions(text, label=label, errors=errors)
        _check_resource_bounds(text, label=label, errors=errors)

    _check_publish_workflow(root, errors)
    _check_dependency_review_workflow(root, errors)


def _check_runner_policy(text: str, *, label: str, errors: list[str]) -> None:
    runs_on = workflow_runs_on_lines(text)
    if not runs_on:
        return
    for line in runs_on:
        if "self-hosted" in line:
            errors.append(
                f"workflow must not use self-hosted runners (GitHub-hosted only): {label}: {line}"
            )
        for marker in _PRIVATE_LABEL_MARKERS:
            if marker in line.lower() and "self-hosted" not in line:
                errors.append(
                    f"workflow must not reference private runner labels or groups: {label}: {line}"
                )
        if not any(hosted in line for hosted in HOSTED_RUNNERS):
            errors.append(f"workflow job must run on a GitHub-hosted runner: {label}: {line}")


def _check_events(text: str, *, label: str, errors: list[str]) -> None:
    if "pull_request_target:" in text:
        errors.append(
            f"workflow must not use pull_request_target for contributor execution: {label}"
        )
    if "pull_request:" in text and "secrets." in text:
        errors.append(f"pull-request CI must be secret-free: {label}")


def _check_credentials(text: str, *, label: str, errors: list[str]) -> None:
    if "actions/checkout" in text and "persist-credentials: false" not in text:
        errors.append(f"workflow checkout must not persist repository credentials: {label}")
    for credential in ("PYPI_API_TOKEN", "password:", "username:", "GH_TOKEN:"):
        if credential in text:
            errors.append(
                f"workflow must not contain long-lived credential input: {label}: {credential}"
            )


def _check_action_pins(text: str, *, label: str, errors: list[str]) -> None:
    for line in workflow_uses_lines(text):
        if not _PIN.search(line):
            errors.append(
                f"workflow action must be pinned to a 40-character commit SHA: {label}: {line}"
            )


def _check_permissions(text: str, *, label: str, errors: list[str]) -> None:
    if "permissions:" in text and "contents: read" not in text:
        errors.append(f"workflow must retain read-only repository permissions: {label}")
    if "id-token: write" in text and label != ".github/workflows/publish.yml":
        errors.append(f"only the publish workflow may request OIDC id-token: write: {label}")


def _check_resource_bounds(text: str, *, label: str, errors: list[str]) -> None:
    """Require an explicit timeout for every public workflow job and CI cancellation."""

    runner_count = len(workflow_runs_on_lines(text))
    timeout_count = text.count("timeout-minutes:")
    if runner_count and timeout_count != runner_count:
        errors.append(
            f"every public workflow job must have an explicit timeout: {label} "
            f"({timeout_count} timeouts for {runner_count} jobs)"
        )

    if label == ".github/workflows/ci.yml":
        required = (
            "concurrency:",
            "group: ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}",
            "cancel-in-progress: true",
            "timeout-minutes: 45",
            "timeout-minutes: 30",
        )
        for fragment in required:
            if fragment not in text:
                errors.append(f"public CI is missing resource-boundary requirement: {fragment!r}")
    elif label == ".github/workflows/validation.yml" and "timeout-minutes: 120" not in text:
        errors.append("validation workflow must retain its 120-minute bounded timeout")
    elif label == ".github/workflows/publish.yml":
        for fragment in ("timeout-minutes: 60", "timeout-minutes: 15"):
            if fragment not in text:
                errors.append(
                    f"publish workflow is missing resource-boundary requirement: {fragment!r}"
                )


def _check_publish_workflow(root: Path, errors: list[str]) -> None:
    path = root / ".github/workflows/publish.yml"
    if not path.is_file():
        errors.append("missing public publish workflow: .github/workflows/publish.yml")
        return
    publish = path.read_text(encoding="utf-8")
    runs_on = workflow_runs_on_lines(publish)
    if not runs_on or not all("ubuntu-latest" in line for line in runs_on):
        errors.append("publish workflow must run on GitHub-hosted ubuntu-latest")
    if "pull_request:" in publish or "pull_request_target:" in publish:
        errors.append("publish workflow must never be invokable from pull-request events")
    required_fragments = (
        "release:\n    types: [published]",
        "environment:\n      name: pypi",
        "id-token: write",
        "pypa/gh-action-pypi-publish@",
        "python -m twine check dist/*",
        "python scripts/release_check.py --require-release-evidence",
        "scripts/history_scan.py",
        "git merge-base --is-ancestor",
        "ref: ${{ github.event.release.tag_name }}",
        "python scripts/verify_release_tag.py",
        "--allowed-signers .github/release-signers",
        "--expected-principal XiantingWu",
    )
    for fragment in required_fragments:
        if fragment not in publish:
            errors.append(f"publish workflow missing release safety requirement: {fragment!r}")
    current_head_gate = (
        'TAG_COMMIT="$(git rev-parse "${GITHUB_REF_NAME}^{commit}")"',
        'MAIN_COMMIT="$(git rev-parse origin/main)"',
        'test "$TAG_COMMIT" = "$MAIN_COMMIT"',
    )
    if not all(fragment in publish for fragment in current_head_gate):
        errors.append(
            "publish workflow must require the tag commit to equal the current canonical main head"
        )
    for fragment in ("PYPI_API_TOKEN", "password:", "username:"):
        if fragment in publish:
            errors.append(
                f"publish workflow must not contain long-lived credential input: {fragment!r}"
            )
    if "github.event.release.target_commitish" in publish:
        errors.append("publish workflow must check out the release tag, not target_commitish")
    if "grep -Eq" in publish and "SIGNATURE" in publish:
        errors.append(
            "publish workflow must use cryptographic tag verification, not signature-block text"
        )


def _check_dependency_review_workflow(root: Path, errors: list[str]) -> None:
    path = root / ".github/workflows/dependency-review.yml"
    if not path.is_file():
        errors.append("missing public dependency-review workflow")
        return
    text = path.read_text(encoding="utf-8")
    if "pull_request:" not in text:
        errors.append("dependency-review workflow must trigger on pull_request")
    for event in ("push:", "pull_request_target:", "workflow_dispatch:", "schedule:"):
        if event in text:
            errors.append(f"dependency-review workflow must not contain {event}")
    for fragment in (
        "name: Dependency Review",
        "permissions:\n  contents: read",
        "actions/dependency-review-action@",
        "fail-on-severity: high",
        "timeout-minutes:",
    ):
        if fragment not in text:
            errors.append(f"dependency-review workflow missing safety requirement: {fragment!r}")
    for fragment in ("contents: write", "actions: write", "id-token: write", "secrets."):
        if fragment in text:
            errors.append(
                f"dependency-review workflow must not request privileged or secret access: {fragment!r}"
            )
