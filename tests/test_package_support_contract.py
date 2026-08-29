from __future__ import annotations

import tomllib
from copy import deepcopy
from pathlib import Path

from scripts.release_checks.package_surface import (
    EXPECTED_REQUIRES_PYTHON,
    check_package_surface,
)

ROOT = Path(__file__).parents[1]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_package_support_range_matches_certified_python_minors() -> None:
    payload = _pyproject()
    assert payload["project"]["requires-python"] == EXPECTED_REQUIRES_PYTHON
    classifiers = set(payload["project"]["classifiers"])
    for minor in ("3.11", "3.12", "3.13"):
        assert f"Programming Language :: Python :: {minor}" in classifiers


def test_release_check_rejects_unbounded_future_python_claim() -> None:
    payload = deepcopy(_pyproject())
    payload["project"]["requires-python"] = ">=3.11"
    errors: list[str] = []
    check_package_surface(ROOT, payload, errors)
    assert any("requires-python" in error for error in errors)
