from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__:
    from .release_checks.benchmark_surface import check_release_evidence, check_smoke_corpus
    from .release_checks.certification_surface import check_certification_surface
    from .release_checks.common import BASE_REQUIRED_FILES, PUBLIC_WORKFLOWS
    from .release_checks.package_surface import (
        check_package_surface,
        check_required_files,
        load_pyproject,
    )
    from .release_checks.public_contract_surface import check_public_contract_surface
    from .release_checks.security_surface import check_security_surface
    from .release_checks.workflow_surface import check_workflow_surface
else:
    from release_checks.benchmark_surface import check_release_evidence, check_smoke_corpus
    from release_checks.certification_surface import check_certification_surface
    from release_checks.common import BASE_REQUIRED_FILES, PUBLIC_WORKFLOWS
    from release_checks.package_surface import (
        check_package_surface,
        check_required_files,
        load_pyproject,
    )
    from release_checks.public_contract_surface import check_public_contract_surface
    from release_checks.security_surface import check_security_surface
    from release_checks.workflow_surface import check_workflow_surface

ROOT = Path(__file__).resolve().parents[1]

__all__ = [
    "BASE_REQUIRED_FILES",
    "PUBLIC_WORKFLOWS",
    "check_release_tree",
    "main",
]


def check_release_tree(
    root: Path = ROOT,
    *,
    require_release_evidence: bool = False,
) -> list[str]:
    """Validate the complete public-release tree from composable policy layers."""
    root = Path(root).resolve()
    errors: list[str] = []

    check_required_files(root, errors)
    pyproject = load_pyproject(root, errors)
    if pyproject is None:
        return errors

    version = check_package_surface(root, pyproject, errors)
    check_security_surface(root, errors)
    check_public_contract_surface(root, errors)
    check_certification_surface(root, errors)
    check_smoke_corpus(root, version=version, errors=errors)
    if require_release_evidence:
        check_release_evidence(root, version=version, errors=errors)
    check_workflow_surface(root, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the VeriRepro public-release tree.")
    parser.add_argument(
        "--require-release-evidence",
        action="store_true",
        help=(
            "require version-matched front-half and ReproBench benchmark evidence with "
            "trusted GitHub Actions provenance"
        ),
    )
    args = parser.parse_args()
    errors = check_release_tree(require_release_evidence=args.require_release_evidence)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    mode = "final release" if args.require_release_evidence else "source"
    print(f"PASS: VeriRepro {mode} tree checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
