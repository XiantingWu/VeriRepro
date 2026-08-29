from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_checker():
    root = Path(__file__).parents[1]
    script = root / "scripts/certification_environment_check.py"
    spec = importlib.util.spec_from_file_location("certification_environment_check", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_certification_constraints_require_exact_sorted_pins(tmp_path: Path) -> None:
    checker = _load_checker()
    path = tmp_path / "constraints.txt"
    path.write_text("pytest>=8\n", encoding="utf-8")
    with pytest.raises(checker.CertificationEnvironmentError, match="exactly one =="):
        checker._active_exact_requirements(path)

    path.write_text("pytest==8.4.2\npackaging==26.3\n", encoding="utf-8")
    with pytest.raises(checker.CertificationEnvironmentError, match="sorted"):
        checker._active_exact_requirements(path)


def test_certification_constraints_honor_python_markers(tmp_path: Path) -> None:
    checker = _load_checker()
    path = tmp_path / "constraints.txt"
    path.write_text(
        'packaging==26.3\nzipp==4.1.0 ; python_version < "3.0"\n',
        encoding="utf-8",
    )
    active = checker._active_exact_requirements(path)
    assert [item.name for item in active] == ["packaging"]
