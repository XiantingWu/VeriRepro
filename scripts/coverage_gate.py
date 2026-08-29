from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

DEFAULT_MIN_STATEMENT = 85.0
DEFAULT_MIN_BRANCH = 75.0


def _load_totals(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"coverage JSON must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not parse coverage JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("totals"), dict):
        raise ValueError("coverage JSON must contain a totals object")
    return payload["totals"]


def coverage_percentages(path: Path) -> tuple[float, float]:
    totals = _load_totals(path)
    try:
        statement = float(totals["percent_covered"])
        branches = int(totals.get("num_branches", 0))
        covered_branches = int(totals.get("covered_branches", 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("coverage totals contain invalid numeric values") from exc
    if not math.isfinite(statement) or statement < 0.0 or statement > 100.0:
        raise ValueError("statement coverage must be a finite percentage between 0 and 100")
    if branches < 0 or covered_branches < 0 or covered_branches > branches:
        raise ValueError("branch coverage counts are inconsistent")
    branch = 100.0 if branches == 0 else covered_branches * 100.0 / branches
    return statement, branch


def check_coverage(
    path: Path,
    *,
    min_statement: float = DEFAULT_MIN_STATEMENT,
    min_branch: float = DEFAULT_MIN_BRANCH,
) -> list[str]:
    if not math.isfinite(min_statement) or not 0.0 <= min_statement <= 100.0:
        return ["minimum statement coverage must be between 0 and 100"]
    if not math.isfinite(min_branch) or not 0.0 <= min_branch <= 100.0:
        return ["minimum branch coverage must be between 0 and 100"]
    try:
        statement, branch = coverage_percentages(path)
    except ValueError as exc:
        return [str(exc)]

    errors: list[str] = []
    if statement < min_statement:
        errors.append(f"statement coverage {statement:.1f}% is below required {min_statement:.1f}%")
    if branch < min_branch:
        errors.append(f"branch coverage {branch:.1f}% is below required {min_branch:.1f}%")
    if not errors:
        print(f"VERIREPRO_COVERAGE statement={statement:.1f}% branch={branch:.1f}%")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce VeriRepro release coverage floors.")
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--min-statement", type=float, default=DEFAULT_MIN_STATEMENT)
    parser.add_argument("--min-branch", type=float, default=DEFAULT_MIN_BRANCH)
    args = parser.parse_args()
    errors = check_coverage(
        args.coverage_json,
        min_statement=args.min_statement,
        min_branch=args.min_branch,
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
