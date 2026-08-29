from __future__ import annotations

import json
import re
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .intelligence import PaperIntelligence
from .llm import LLMConfig, OpenAICompatibleClient


@dataclass(frozen=True)
class RepositoryPlan:
    command: str | None
    entrypoint: str | None
    rationale: str
    evidence_file: str | None
    evidence_quote: str | None
    verification: str
    model: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SYSTEM_PROMPT = """You are planning a computational paper reproduction from an already-cloned repository.
Return JSON only:
{
  "command": string|null,
  "entrypoint": string|null,
  "rationale": string,
  "evidence_file": string|null,
  "evidence_quote": string|null
}
Rules:
- Prefer an explicit reproduction/evaluation script documented by the repository.
- The entrypoint must be one of the candidate files supplied by the caller.
- The command may only invoke Python or Jupyter on that entrypoint. Do not use shell pipelines, redirects, curl, wget, rm, sudo, package managers, or network utilities.
- Do not invent files or flags that are not supported by the supplied repository evidence.
- If no defensible command exists, return null command/entrypoint.
"""

_TEXT_FILES = (
    "README.md",
    "README.rst",
    "README.txt",
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "environment.yml",
    "environment.yaml",
)
_MAX_ENTRYPOINT_SCAN = 5000
_MAX_EVIDENCE_FILE_CHARS = 100_000


def _safe_repo_file(repo: Path, path: Path) -> bool:
    if path.is_symlink():
        return False
    try:
        root = repo.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    return resolved.is_file()


def _read_repo_text(repo: Path, path: Path, limit: int) -> str:
    if limit <= 0 or not _safe_repo_file(repo, path):
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def _candidate_entrypoints(repo: Path, limit: int = 120) -> tuple[str, ...]:
    candidates: list[str] = []
    preferred_tokens = (
        "repro",
        "eval",
        "test",
        "infer",
        "train",
        "experiment",
        "benchmark",
        "main",
    )
    scanned = 0
    for pattern in ("*.py", "*.ipynb"):
        for path in repo.rglob(pattern):
            scanned += 1
            if scanned > _MAX_ENTRYPOINT_SCAN:
                break
            if not _safe_repo_file(repo, path):
                continue
            relative = path.relative_to(repo)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if any(token in path.name.lower() for token in preferred_tokens):
                candidates.append(relative.as_posix())
                if len(candidates) >= limit:
                    return tuple(sorted(dict.fromkeys(candidates)))
        if scanned > _MAX_ENTRYPOINT_SCAN:
            break
    return tuple(sorted(dict.fromkeys(candidates)))


def _repository_context(repo: Path, candidates: tuple[str, ...], max_chars: int = 55_000) -> str:
    chunks = ["Candidate entrypoints:\n" + "\n".join(f"- {item}" for item in candidates)]
    used = len(chunks[0])
    for name in _TEXT_FILES:
        remaining = max_chars - used
        if remaining <= 200:
            break
        path = repo / name
        header = f"\n--- FILE {name} ---\n"
        body_budget = max(0, min(_MAX_EVIDENCE_FILE_CHARS, remaining - len(header) - 1))
        if body_budget <= 0:
            break
        text = _read_repo_text(repo, path, body_budget)
        if not text:
            continue
        chunk = f"{header}{text}\n"
        chunks.append(chunk)
        used += len(chunk)
    return "".join(chunks)[:max_chars]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _safe_evidence_path(repo: Path, filename: str | None) -> Path | None:
    if not filename or filename not in _TEXT_FILES:
        return None
    path = repo / filename
    if not _safe_repo_file(repo, path):
        return None
    return path


def _verify_file_quote(repo: Path, filename: str | None, quote: str | None) -> str:
    if not quote:
        return "unverified"
    path = _safe_evidence_path(repo, filename)
    if path is None:
        return "unverified"
    content = _normalize(_read_repo_text(repo, path, _MAX_EVIDENCE_FILE_CHARS))
    quoted = _normalize(quote)
    if quoted and quoted in content:
        return "verified"
    return "unverified"


def _verify_command_documented(repo: Path, filename: str | None, safe_command: str | None) -> bool:
    if not safe_command:
        return False
    path = _safe_evidence_path(repo, filename)
    if path is None:
        return False
    content = _normalize(_read_repo_text(repo, path, _MAX_EVIDENCE_FILE_CHARS))
    return _normalize(safe_command) in content


def _validate_command(
    command: str | None, entrypoint: str | None, candidates: tuple[str, ...]
) -> str | None:
    if not command or not entrypoint or entrypoint not in candidates:
        return None
    # The validated string is ultimately passed to `sh -lc` inside the container.
    # Reject every command separator/control form before tokenization, then rebuild
    # the accepted argv with shell quoting so model-supplied arguments remain data.
    if any(token in command for token in ("\n", "\r", "\x00", ";", "&", "|", ">", "<", "`", "$(")):
        return None
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv:
        return None
    if argv[0] in {"python", "python3"}:
        if len(argv) < 2 or argv[1] != entrypoint or not entrypoint.endswith(".py"):
            return None
        return shlex.join(argv)
    if argv[:4] == ["jupyter", "nbconvert", "--to", "notebook"]:
        if entrypoint not in argv or not entrypoint.endswith(".ipynb"):
            return None
        allowed = {
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--output",
            entrypoint,
            "/repro-output/executed.ipynb",
        }
        if any(arg not in allowed for arg in argv):
            return None
        return shlex.join(argv)
    return None


def plan_repository_execution(
    repo: Path,
    paper_intelligence: PaperIntelligence | None,
    *,
    model: str | None = None,
    client: OpenAICompatibleClient | None = None,
) -> RepositoryPlan | None:
    candidates = _candidate_entrypoints(repo)
    if not candidates:
        return None
    if client is None:
        config = LLMConfig.from_env(model=model)
        if config is None:
            return None
        client = OpenAICompatibleClient(config)
        resolved_model = config.model
    else:
        resolved_model = (
            getattr(getattr(client, "config", None), "model", None) or model or "custom"
        )

    paper_block = (
        json.dumps(paper_intelligence.to_dict(), indent=2) if paper_intelligence else "null"
    )
    payload = client.complete_json(
        system=_SYSTEM_PROMPT,
        user=(
            "Grounded paper intelligence:\n"
            f"{paper_block}\n\n"
            "Repository evidence:\n"
            f"{_repository_context(repo, candidates)}"
        ),
        max_tokens=2500,
    )
    entrypoint = str(payload.get("entrypoint") or "").strip() or None
    command = str(payload.get("command") or "").strip() or None
    evidence_file = str(payload.get("evidence_file") or "").strip() or None
    evidence_quote = str(payload.get("evidence_quote") or "").strip() or None
    verification = _verify_file_quote(repo, evidence_file, evidence_quote)
    safe_command = _validate_command(command, entrypoint, candidates)
    if verification != "verified" or not _verify_command_documented(
        repo, evidence_file, safe_command
    ):
        safe_command = None

    return RepositoryPlan(
        command=safe_command,
        entrypoint=entrypoint if entrypoint in candidates else None,
        rationale=str(payload.get("rationale") or "").strip(),
        evidence_file=evidence_file,
        evidence_quote=evidence_quote,
        verification=verification,
        model=resolved_model,
    )


def write_repository_plan(plan: RepositoryPlan, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    return destination
