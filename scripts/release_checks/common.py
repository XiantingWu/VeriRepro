from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

BASE_REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CITATION.cff",
    "ROADMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/CANONICAL_IDENTITY.md",
    "docs/TRUST_MODEL.md",
    "docs/MODEL_ENDPOINTS.md",
    "docs/DATASETS.md",
    "docs/SCHEMAS.md",
    "docs/REAL_PAPER_SMOKE.md",
    "docs/REPROBENCH.md",
    "docs/PUBLISHING.md",
    "docs/PUBLIC_RELEASE_CHECKLIST.md",
    "benchmarks/real-paper-smoke.json",
    "benchmarks/reprobench-seed-suite.json",
    "scripts/history_scan.py",
    "scripts/run_real_paper_smoke.py",
    "scripts/run_reprobench_seed.py",
    "src/verirepro/__init__.py",
    "src/verirepro/cli.py",
    "src/verirepro/__main__.py",
    "src/verirepro/reprobench.py",
    "src/verirepro/py.typed",
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/dependency-review.yml",
    ".github/workflows/validation.yml",
    ".github/workflows/publish.yml",
)

PUBLIC_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/dependency-review.yml",
    ".github/workflows/validation.yml",
    ".github/workflows/publish.yml",
)

PINNED_ARXIV_SOURCE = re.compile(r"^\d{4}\.\d{4,5}v\d+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
VALID_REPROBENCH_OUTCOMES = frozenset({"success", "partial", "failure"})
SOFT_PARTIAL_TAXONOMY = "insufficient_evidence_or_execution"
SENSITIVE_RESULT_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "base_url",
        "endpoint",
        "headers",
        "prompt",
        "response",
        "workspace",
        "workspace_root",
    }
)
HOST_PATH_MARKERS = ("/Users/", "/home/", "\\Users\\", "\\home\\")


def contains_sensitive_evidence(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SENSITIVE_RESULT_KEYS:
                return True
            if contains_sensitive_evidence(child):
                return True
        return False
    if isinstance(value, list):
        return any(contains_sensitive_evidence(item) for item in value)
    if isinstance(value, str):
        return any(marker in value for marker in HOST_PATH_MARKERS)
    return False


def workflow_uses_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if "uses:" in line]


def command_gate(text: str, command: str) -> bool:
    """Match `python -m X ...` gates that may run through an isolated venv
    (`"$VENV/bin/python" -m X ...`) inside trusted workflows."""
    import re as _re

    suffix = _re.escape(command.removeprefix("python "))
    return bool(_re.search(rf'(?:"\S*/bin/python"|\bpython)\s+{suffix}', text))


def workflow_runs_on_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if re.match(r"^\s*runs-on\s*:", line)]


def version_tuple(version: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_at_least(version: str, minimum: tuple[int, int, int]) -> bool:
    parsed = version_tuple(version)
    return parsed is not None and parsed >= minimum


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_relative_path(value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{field} must be a non-empty relative path")
    normalized = value.replace("\\", "/")
    if (
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise ValueError(f"{field} must be a confined relative path")
    return Path(normalized)


def json_object(path: Path, *, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"could not parse {label}: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label} must contain a JSON object")
        return None
    return payload
