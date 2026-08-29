from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

from reproagent.release_provenance import (
    TRUSTED_CERTIFICATION_WORKFLOWS,
    release_source_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONSTRAINTS = ROOT / "constraints/certification.txt"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_DECIMAL_ID = re.compile(r"^[1-9][0-9]*$")


class CertificationEnvironmentError(ValueError):
    pass


def _active_exact_requirements(path: Path) -> list[Requirement]:
    if path.is_symlink() or not path.is_file():
        raise CertificationEnvironmentError(f"unsafe or missing constraints file: {path}")
    requirements: list[Requirement] = []
    seen: set[str] = set()
    previous = ""
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            requirement = Requirement(line)
        except Exception as exc:
            raise CertificationEnvironmentError(
                f"invalid constraint at line {line_number}: {line!r}"
            ) from exc
        if requirement.url or requirement.extras:
            raise CertificationEnvironmentError(
                f"constraint must be a plain exact package pin at line {line_number}: {line!r}"
            )
        specs = list(requirement.specifier)
        if len(specs) != 1 or specs[0].operator != "==":
            raise CertificationEnvironmentError(
                f"constraint must use exactly one == pin at line {line_number}: {line!r}"
            )
        canonical = re.sub(r"[-_.]+", "-", requirement.name).lower()
        if canonical in seen:
            raise CertificationEnvironmentError(f"duplicate constrained package: {canonical}")
        if previous and canonical < previous:
            raise CertificationEnvironmentError(
                "constraints must remain sorted by canonical package name"
            )
        seen.add(canonical)
        previous = canonical
        if requirement.marker is None or requirement.marker.evaluate():
            requirements.append(requirement)
    if not requirements:
        raise CertificationEnvironmentError("no active certification constraints")
    return requirements


def certification_snapshot(
    constraints: Path = DEFAULT_CONSTRAINTS,
    *,
    root: Path = ROOT,
    run_id: str | None = None,
    head_sha: str | None = None,
) -> dict[str, object]:
    requirements = _active_exact_requirements(constraints)
    packages: dict[str, str] = {}
    for requirement in requirements:
        expected = next(iter(requirement.specifier)).version
        try:
            actual = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise CertificationEnvironmentError(
                f"constrained package is not installed: {requirement.name}=={expected}"
            ) from exc
        if Version(actual) != Version(expected):
            raise CertificationEnvironmentError(
                f"constrained package drift: {requirement.name} expected {expected}, got {actual}"
            )
        packages[re.sub(r"[-_.]+", "-", requirement.name).lower()] = actual

    constraint_path = constraints.resolve()
    root = root.resolve()
    try:
        relative_constraint = constraint_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise CertificationEnvironmentError(
            "constraints path must stay inside repository root"
        ) from exc

    payload: dict[str, object] = {
        "schema_version": 1,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "constraints": relative_constraint,
        "constraints_sha256": hashlib.sha256(constraint_path.read_bytes()).hexdigest(),
        "release_source_sha256": release_source_sha256(root),
        "packages": dict(sorted(packages.items())),
    }
    if run_id is not None or head_sha is not None:
        normalized_run = str(run_id or "").strip()
        normalized_head = str(head_sha or "").strip().lower()
        if not _DECIMAL_ID.fullmatch(normalized_run):
            raise CertificationEnvironmentError("run id must be a positive decimal integer")
        if not _SHA40.fullmatch(normalized_head):
            raise CertificationEnvironmentError("head SHA must be a 40-character Git SHA")
        workflow = os.environ.get("GITHUB_WORKFLOW", "").strip()
        if workflow not in TRUSTED_CERTIFICATION_WORKFLOWS:
            raise CertificationEnvironmentError(
                "environment provenance must come from an approved certification workflow"
            )
        payload["provenance"] = {
            "workflow": workflow,
            "github_actions_run_id": normalized_run,
            "head_sha": normalized_head,
        }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed unless the active certification environment matches committed exact constraints."
    )
    parser.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--head-sha")
    args = parser.parse_args()
    try:
        payload = certification_snapshot(
            args.constraints,
            run_id=args.run_id,
            head_sha=args.head_sha,
        )
    except (OSError, ValueError, CertificationEnvironmentError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    if args.json or args.output is None:
        print(rendered, end="")
    else:
        print(
            "PASS: certification environment matches exact committed constraints "
            f"({payload['constraints_sha256']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
