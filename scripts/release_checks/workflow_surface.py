from __future__ import annotations

import re
from pathlib import Path

from .common import PUBLIC_WORKFLOWS, command_gate, workflow_runs_on_lines, workflow_uses_lines


def check_workflow_surface(root: Path, errors: list[str]) -> None:
    _check_contribution_and_runner_policy(root, errors)
    _check_quality_workflow(root, errors)
    _check_validation_workflow(root, errors)
    _check_trusted_smoke_workflows(root, errors)
    _check_action_pins(root, errors)
    _check_publish_workflow(root, errors)


def _check_contribution_and_runner_policy(root: Path, errors: list[str]) -> None:
    workflows = root / ".github/workflows"
    legacy_ci = workflows / "ci.yml"
    if legacy_ci.exists():
        errors.append(
            "hosted public CI must remain removed; external pull requests are review-only until "
            "a maintainer promotes reviewed code to a trusted integration branch"
        )

    if not workflows.is_dir():
        return

    for path in sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml"))):
        text = path.read_text(encoding="utf-8")
        label = path.relative_to(root).as_posix()
        if "pull_request_target:" in text:
            errors.append(f"workflow must not use pull_request_target: {label}")
        if "pull_request:" in text:
            errors.append(
                f"workflow must not execute pull-request events under the review-only fork policy: {label}"
            )

        # VeriRepro deliberately has no GitHub-hosted CI/test lane. The publish
        # workflow is the sole exception: PyPA's official Trusted Publishing
        # action is a Linux container action and is kept isolated from source
        # validation and pull-request events.
        if path.name != "publish.yml":
            for line in workflow_runs_on_lines(text):
                if any(
                    hosted in line for hosted in ("ubuntu-latest", "windows-latest", "macos-latest")
                ):
                    errors.append(
                        f"non-publish workflow must not depend on GitHub-hosted runners: {label}: {line}"
                    )


def _require_coverage_floor(text: str, *, label: str, errors: list[str]) -> None:
    required = (
        "scripts/coverage_gate.py",
        "--min-statement 85",
        "--min-branch 75",
    )
    for fragment in required:
        if fragment not in text:
            errors.append(f"{label} must fail closed on release coverage floors: {fragment}")


def _check_quality_workflow(root: Path, errors: list[str]) -> None:
    path = root / ".github/workflows/quality.yml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    runs_on = workflow_runs_on_lines(text)
    if not runs_on or not all(
        "self-hosted" in line and "macOS" in line and "ARM64" in line for line in runs_on
    ):
        errors.append("quality workflow must run on a trusted self-hosted macOS ARM64 runner")
    if not runs_on or not all(
        "repo-repo1-verirepro" in line and "verirepro-release" in line for line in runs_on
    ):
        errors.append(
            "quality workflow must run only on the dedicated Repo1 standalone runner "
            "(repo-repo1-verirepro + verirepro-release)"
        )
    if "pull_request:" in text:
        errors.append("quality workflow must not run on pull_request events")
    if "workflow_dispatch:" not in text or "push:" not in text:
        errors.append("quality workflow must support owner-controlled push and manual dispatch")
    if "integration/**" not in text or "startsWith(github.ref_name, 'integration/')" not in text:
        errors.append(
            "quality workflow must support reviewed maintainer integration/** branches without "
            "executing fork pull-request events directly"
        )
    if "github.actor == github.repository_owner" not in text:
        errors.append(
            "quality workflow must require the repository owner before self-hosted execution"
        )
    if "ref: ${{ github.sha }}" not in text or "git rev-parse HEAD" not in text:
        errors.append("quality workflow must certify the exact event SHA")
    if "secrets." in text:
        errors.append("quality workflow must not require repository secrets")
    if "persist-credentials: false" not in text:
        errors.append("quality workflow checkout must not persist repository credentials")
    for required in (
        "ruff",
        "mypy",
        "--cov-branch",
        "scripts/release_check.py",
        "scripts/launch_surface_check.py",
        "twine",
    ):
        if required not in text:
            errors.append(f"quality workflow missing required quality gate: {required}")
    if "format --check src tests scripts" not in text:
        errors.append("quality workflow missing required quality gate: ruff format --check")
    history_requirements = (
        "scripts/history_scan.py",
        'if [ "$GITHUB_REF_NAME" = "main" ]',
        "fetch --force --no-tags origin main:refs/remotes/origin/main",
        "VERIREPRO_READ_TOKEN: ${{ github.token }}",
        "AUTHORIZATION: basic",
        "unset AUTH_HEADER VERIREPRO_READ_TOKEN",
        "--ref origin/main",
        "--include-tree HEAD",
    )
    for fragment in history_requirements:
        if fragment not in text:
            errors.append(
                "quality workflow must scan final main history or durable main plus the exact candidate tree: "
                f"{fragment}"
            )
    _require_coverage_floor(text, label="quality workflow", errors=errors)
    if not command_gate(text, "python -m build"):
        errors.append("quality workflow missing required quality gate: python -m build")

    compatibility_requirements = (
        "python-compatibility:",
        "needs: certify",
        "python: ['3.12', '3.13']",
        "_kit/bin/ensure-python-runtime.sh",
        'bash "$selector" "${{ matrix.python }}"',
        "VERIREPRO_COMPAT_PY",
        "sys.version_info[:2]",
        '"$VENV/bin/python" -m pytest -q',
    )
    for fragment in compatibility_requirements:
        if fragment not in text:
            errors.append(
                "quality workflow must verify advertised Python 3.12/3.13 compatibility using "
                f"runner-manager-provisioned runtimes: {fragment}"
            )
    if "actions/setup-python@" in text:
        errors.append(
            "quality compatibility lane must not use actions/setup-python on the no-sudo persistent "
            "macOS runner; use the runner-manager managed-runtime selector"
        )


def _check_validation_workflow(root: Path, errors: list[str]) -> None:
    path = root / ".github/workflows/validation.yml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    runs_on = workflow_runs_on_lines(text)
    if "name: VeriRepro validation" not in text:
        errors.append("trusted evidence producer must be named exactly 'VeriRepro validation'")
    if not runs_on or not all(
        "self-hosted" in line and "macOS" in line and "ARM64" in line for line in runs_on
    ):
        errors.append("validation workflow must run only on trusted self-hosted macOS ARM64 jobs")
    if not runs_on or not all(
        "repo-repo1-verirepro" in line and ("verirepro-release" in line or "verirepro-ci" in line)
        for line in runs_on
    ):
        errors.append(
            "validation workflow jobs must run only on the dedicated Repo1 standalone runner "
            "(repo-repo1-verirepro with verirepro-release or verirepro-ci)"
        )
    if "verirepro-release" not in text:
        errors.append(
            "validation workflow must reserve verirepro-release for its trusted certification job"
        )
    if "pull_request:" in text:
        errors.append("validation workflow must never run on pull_request events")
    if "workflow_dispatch:" not in text or "validation/**" not in text:
        errors.append(
            "validation workflow must support owner dispatch and dedicated validation branches"
        )
    if "github.actor == github.repository_owner" not in text:
        errors.append(
            "validation workflow must require the repository owner before self-hosted execution"
        )
    if "ref: ${{ github.sha }}" not in text or "git rev-parse HEAD" not in text:
        errors.append("validation workflow must measure and hand off the exact event SHA")
    if "persist-credentials: false" not in text:
        errors.append("validation checkout must not persist repository credentials")
    if "secrets." in text:
        errors.append("validation workflow must not depend on repository secrets")
    if "actions/upload-artifact@" in text:
        errors.append(
            "validation workflow must not require GitHub artifact storage for release evidence"
        )

    if "certify:" not in text or "evidence-writeback:" not in text or "needs: certify" not in text:
        errors.append("validation must separate read-only certification from evidence writeback")
    if "permissions:\n      contents: read" not in text:
        errors.append("validation certify job must explicitly retain contents: read")
    if "permissions:\n      contents: write" not in text:
        errors.append(
            "validation evidence-writeback job must be the explicit contents: write boundary"
        )

    writeback = text.split("evidence-writeback:", 1)[1] if "evidence-writeback:" in text else ""
    for forbidden in ("python -m pytest", "ruff", "mypy", "pip install", "scripts/", "docker "):
        if forbidden in writeback:
            errors.append(
                "validation evidence-writeback must not execute project code or dependencies: "
                f"{forbidden}"
            )

    for required in (
        "--cov-branch",
        "scripts/run_real_paper_smoke.py",
        "--require-top1",
        "--require-evidence",
        "--inspect-repositories",
        "--require-environment-plan",
        "--max-cases 3",
        "scripts/stamp_release_measurement.py",
        "scripts/run_reprobench_seed.py",
        "scripts/record_release_evidence.py",
        "scripts/release_check.py --require-release-evidence",
        "scripts/release_source_check.py",
        "evidence/verirepro-",
        "evidence.sha256",
        "SOURCE_SHA",
        "RUNNER_NAME",
        "shasum -a 256 -c",
        "x-access-token",
        "AUTHORIZATION: basic",
    ):
        if required not in text:
            errors.append(f"validation workflow missing trusted evidence requirement: {required}")
    if "format --check src tests scripts" not in text:
        errors.append("validation workflow missing required quality gate: ruff format --check")
    if "scripts/history_scan.py" not in text:
        errors.append(
            "validation workflow must scan all reachable Git history before evidence promotion"
        )
    _require_coverage_floor(text, label="validation workflow", errors=errors)


def _check_trusted_smoke_workflows(root: Path, errors: list[str]) -> None:
    smoke_workflows = (
        ".github/workflows/litellm-smoke.yml",
        ".github/workflows/real-paper-smoke.yml",
    )
    for workflow in smoke_workflows:
        path = root / workflow
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        runs_on = workflow_runs_on_lines(text)
        if not runs_on or not all(
            "experiments" in line and "self-hosted" in line for line in runs_on
        ):
            errors.append(f"{workflow} must target the trusted experiments runner")
        if "paper1" in text or "paper2" in text:
            errors.append(f"{workflow} must not reference frozen paper runners")
        if "workflow_dispatch:" not in text:
            errors.append(f"{workflow} must remain maintainer-dispatched")
        if "actions/upload-artifact@" in text or "actions/download-artifact@" in text:
            errors.append(
                f"{workflow} must keep networked smoke output transient instead of publishing GitHub artifacts"
            )


def _check_action_pins(root: Path, errors: list[str]) -> None:
    for workflow in PUBLIC_WORKFLOWS:
        path = root / workflow
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for line in workflow_uses_lines(text):
            if not re.search(r"@[0-9a-f]{40}(?:\s|$)", line):
                errors.append(
                    "public workflow action must be pinned to a 40-character "
                    f"commit SHA: {workflow}: {line}"
                )


def _check_publish_workflow(root: Path, errors: list[str]) -> None:
    path = root / ".github/workflows/publish.yml"
    if not path.is_file():
        return
    publish = path.read_text(encoding="utf-8")
    runs_on = workflow_runs_on_lines(publish)
    if not runs_on or not all("ubuntu-latest" in line for line in runs_on):
        errors.append(
            "publish workflow must keep its isolated GNU/Linux lane for PyPA Trusted Publishing"
        )
    if "pull_request:" in publish or "pull_request_target:" in publish:
        errors.append("publish workflow must never be invokable from pull-request events")
    required_fragments = (
        "release:\n    types: [published]",
        "environment:\n      name: pypi",
        "id-token: write",
        "pypa/gh-action-pypi-publish@",
        "python -m twine check dist/*",
        "GITHUB_REF_NAME",
        "python scripts/release_check.py --require-release-evidence",
        "fetch-depth: 0",
        "scripts/history_scan.py",
        "git cat-file -t",
        "BEGIN (PGP|SSH) SIGNATURE",
        "git merge-base --is-ancestor",
    )
    for fragment in required_fragments:
        if fragment not in publish:
            errors.append(f"publish workflow missing release safety requirement: {fragment!r}")
    for fragment in ("PYPI_API_TOKEN", "password:", "username:"):
        if fragment in publish:
            errors.append(
                f"publish workflow must not contain long-lived credential input: {fragment!r}"
            )
