from __future__ import annotations

import hashlib
from pathlib import Path

TRUSTED_CERTIFICATION_WORKFLOWS = frozenset(
    {
        "VeriRepro validation",
    }
)

_RELEASE_SOURCE_FILES = (
    "pyproject.toml",
    "constraints/certification.txt",
    "scripts/certification_environment_check.py",
    "scripts/coverage_gate.py",
    "scripts/history_scan.py",
    "scripts/launch_surface_check.py",
    "scripts/release_check.py",
    "scripts/release_source_check.py",
    "scripts/verify_release_tag.py",
    "scripts/record_release_evidence.py",
    "scripts/run_real_paper_smoke.py",
    "scripts/stamp_release_measurement.py",
    "scripts/run_reprobench_seed.py",
    "src/verirepro/py.typed",
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/dependency-review.yml",
    ".github/workflows/validation.yml",
    ".github/workflows/publish.yml",
)
_RELEASE_SOURCE_GLOBS = (
    "scripts/release_checks/**/*.py",
    "src/reproagent/**/*.py",
    "src/verirepro/**/*.py",
)


def _confined_regular_file(root: Path, candidate: Path, *, label: str) -> Path:
    if candidate.is_symlink():
        raise ValueError(f"release source file must not be a symlink: {label}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"release source path escapes root: {label}") from exc
    if not resolved.is_file():
        raise ValueError(f"release source file is missing or unsafe: {label}")
    return resolved


def release_source_files(root: Path) -> tuple[Path, ...]:
    """Return the deterministic public release source set.

    Benchmark task/suite bytes are bound separately in ReproBench evidence.
    Documentation is intentionally excluded so evidence can be promoted and
    explanatory text improved without invalidating measured runtime results.
    Measurement, evidence-promotion, public-launch policy, final release-policy,
    coverage enforcement, exact maintainer certification dependency constraints,
    package typing markers, dependency-update policy, dependency-review policy,
    and trusted certification/evidence-production plus publish workflows are part of the
    fingerprint because changing those semantics invalidates prior measurements
    even when core runtime Python bytes are unchanged. Public CI workflow bytes
    are part of release-source identity because fork/main quality policy is
    release-relevant. External PR execution is GitHub-hosted, secret-free and
    non-certifying; exact-main validation remains the certification authority.
    """

    root = Path(root).resolve()
    selected: set[Path] = set()
    for relative in _RELEASE_SOURCE_FILES:
        candidate = root / relative
        selected.add(_confined_regular_file(root, candidate, label=relative))

    for pattern in _RELEASE_SOURCE_GLOBS:
        for candidate in root.glob(pattern):
            label = candidate.relative_to(root).as_posix()
            selected.add(_confined_regular_file(root, candidate, label=label))

    if not selected:
        raise ValueError("release source set is empty")
    return tuple(sorted(selected, key=lambda item: item.relative_to(root).as_posix()))


def release_source_sha256(root: Path) -> str:
    """Hash release-relevant source as path + per-file SHA-256 records."""

    root = Path(root).resolve()
    digest = hashlib.sha256()
    for path in release_source_files(root):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        file_digest = hashlib.sha256(path.read_bytes()).digest()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(file_digest)
    return digest.hexdigest()


def release_source_manifest(root: Path) -> list[dict[str, str]]:
    """Return non-secret per-file digests for audit/debugging."""

    root = Path(root).resolve()
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in release_source_files(root)
    ]
