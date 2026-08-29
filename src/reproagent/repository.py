from __future__ import annotations

import hashlib
import re
import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from .models import RepositoryProfile

_DEPENDENCY_CANDIDATES = (
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "environment.yml",
    "environment.yaml",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "conda-lock.yml",
    "conda-lock.yaml",
)
_MANIFEST_CANDIDATES = (
    "verirepro.yaml",
    ".verirepro.yaml",
    "reproagent.yaml",
    ".reproagent.yaml",
)
_GITHUB_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


class RepositorySecurityError(RuntimeError):
    """Raised when a repository source would cross the host trust boundary unsafely."""


def validate_repository_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise RepositorySecurityError(
            "v0.5 repository cloning accepts only HTTPS github.com repository URLs"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RepositorySecurityError(
            "repository URL must not contain credentials, query, or fragment"
        )
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise RepositorySecurityError(
            "repository URL must be exactly https://github.com/<owner>/<repo>"
        )
    owner, repo = parts
    repo = repo.removesuffix(".git")
    if (
        not owner
        or not repo
        or not _GITHUB_PART.fullmatch(owner)
        or not _GITHUB_PART.fullmatch(repo)
    ):
        raise RepositorySecurityError("repository owner/name contains unsupported characters")
    return f"https://github.com/{owner}/{repo}"


def validate_repository_ref(ref: str) -> str:
    value = ref.strip()
    if not _SAFE_REF.fullmatch(value):
        raise RepositorySecurityError("repository ref contains unsupported characters")
    if value.startswith("-") or value.endswith(("/", ".")):
        raise RepositorySecurityError("repository ref has an unsafe boundary")
    if any(token in value for token in ("..", "@{", "//", "\\")):
        raise RepositorySecurityError("repository ref contains an unsafe Git ref sequence")
    return value


def _git_command(*args: str) -> list[str]:
    return [
        "git",
        "-c",
        "protocol.file.allow=never",
        "-c",
        "protocol.ext.allow=never",
        "-c",
        "filter.lfs.smudge=cat",
        "-c",
        "filter.lfs.process=",
        "-c",
        "filter.lfs.required=false",
        *args,
    ]


def clone_repository(url: str, destination: Path, ref: str | None = None) -> Path:
    safe_url = validate_repository_url(url)
    safe_ref = validate_repository_ref(ref) if ref else None
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        _git_command("clone", "--depth", "1", "--no-tags", safe_url, str(destination)),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(f"git clone failed: {process.stderr.strip()}")
    if safe_ref:
        fetch = subprocess.run(
            _git_command(
                "-C", str(destination), "fetch", "--depth", "1", "--no-tags", "origin", safe_ref
            ),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if fetch.returncode != 0:
            raise RuntimeError(f"git fetch {safe_ref!r} failed: {fetch.stderr.strip()}")
        checkout = subprocess.run(
            _git_command("-C", str(destination), "checkout", "--detach", "FETCH_HEAD"),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if checkout.returncode != 0:
            raise RuntimeError(f"git checkout {safe_ref!r} failed: {checkout.stderr.strip()}")
    return destination


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


def _read_text(path: Path, limit: int = 500_000, *, root: Path | None = None) -> str:
    if limit <= 0:
        return ""
    if root is not None and not _safe_repo_file(root, path):
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def _hash_file_into(digest: hashlib._Hash, path: Path) -> None:
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return


def _dependency_text(repo: Path) -> str:
    return "\n".join(
        _read_text(repo / name, root=repo)
        for name in _DEPENDENCY_CANDIDATES
        if _safe_repo_file(repo, repo / name)
    ).lower()


def _detect_stacks(repo: Path) -> tuple[str, ...]:
    dependency_text = _dependency_text(repo)
    stacks = ["Python"]
    if "torch" in dependency_text or "pytorch" in dependency_text:
        stacks.append("PyTorch")
    if "numpy" in dependency_text:
        stacks.append("NumPy")
    if "scipy" in dependency_text:
        stacks.append("SciPy")
    has_notebook = any(_safe_repo_file(repo, path) for path in repo.rglob("*.ipynb"))
    if has_notebook or "jupyter" in dependency_text:
        stacks.append("Jupyter")
    return tuple(stacks)


def _suggest_command(repo: Path) -> str | None:
    candidates = [
        (repo / "reproduce.py", "python reproduce.py"),
        (repo / "scripts" / "reproduce.py", "python scripts/reproduce.py"),
    ]
    for path, command in candidates:
        if _safe_repo_file(repo, path):
            return command

    notebooks = sorted(
        path
        for path in repo.rglob("*.ipynb")
        if "repro" in path.name.lower() and _safe_repo_file(repo, path)
    )
    if notebooks:
        relative = notebooks[0].relative_to(repo)
        quoted = shlex.quote(str(relative))
        return (
            "jupyter nbconvert --to notebook --execute "
            f"{quoted} --output /repro-output/executed.ipynb"
        )
    return None


def _git_commit(repo: Path) -> str | None:
    process = subprocess.run(
        _git_command("-C", str(repo), "rev-parse", "HEAD"),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if process.returncode != 0:
        return None
    value = process.stdout.strip()
    return value if re.fullmatch(r"[0-9a-fA-F]{40}", value) else None


def _python_requirement(repo: Path) -> tuple[str | None, str | None]:
    python_version = repo / ".python-version"
    if _safe_repo_file(repo, python_version):
        match = re.search(r"\b(3\.\d{1,2})(?:\.\d+)?\b", _read_text(python_version, root=repo))
        if match:
            return match.group(1), ".python-version"

    pyproject = repo / "pyproject.toml"
    if _safe_repo_file(repo, pyproject):
        try:
            data = tomllib.loads(_read_text(pyproject, root=repo))
        except tomllib.TOMLDecodeError:
            data = {}
        project = data.get("project") if isinstance(data, dict) else None
        if isinstance(project, dict) and project.get("requires-python"):
            return str(project["requires-python"]), "pyproject.toml:project.requires-python"
        tool = data.get("tool") if isinstance(data, dict) else None
        poetry = tool.get("poetry") if isinstance(tool, dict) else None
        dependencies = poetry.get("dependencies") if isinstance(poetry, dict) else None
        if isinstance(dependencies, dict) and dependencies.get("python"):
            return str(dependencies["python"]), "pyproject.toml:tool.poetry.dependencies.python"

    pipfile = repo / "Pipfile"
    if _safe_repo_file(repo, pipfile):
        try:
            data = tomllib.loads(_read_text(pipfile, root=repo))
        except tomllib.TOMLDecodeError:
            data = {}
        requires = data.get("requires") if isinstance(data, dict) else None
        if isinstance(requires, dict):
            for key in ("python_full_version", "python_version"):
                value = requires.get(key)
                if value:
                    return str(value), f"Pipfile:requires.{key}"

    for name in ("environment.yml", "environment.yaml"):
        path = repo / name
        if _safe_repo_file(repo, path):
            match = re.search(
                r"(?im)^\s*-?\s*python\s*[=~<>! ]+\s*(3\.\d{1,2})",
                _read_text(path, root=repo),
            )
            if match:
                return match.group(1), name

    for name in ("Dockerfile", "docker/Dockerfile"):
        path = repo / name
        if _safe_repo_file(repo, path):
            match = re.search(
                r"(?im)^\s*FROM\s+python:(3\.\d{1,2})",
                _read_text(path, root=repo),
            )
            if match:
                return match.group(1), name
    return None, None


def _dependency_strategy(repo: Path) -> str:
    def has(name: str) -> bool:
        return _safe_repo_file(repo, repo / name)

    if has("uv.lock") and has("pyproject.toml"):
        return "uv"
    if has("poetry.lock") and has("pyproject.toml"):
        return "poetry"
    if has("conda-lock.yml") or has("conda-lock.yaml"):
        return "conda-lock"
    if has("Pipfile") and has("Pipfile.lock"):
        return "pipenv-lock"
    if has("requirements.txt"):
        return "requirements"
    if has("pyproject.toml"):
        return "pyproject"
    if has("setup.py"):
        return "setup"
    if has("environment.yml") or has("environment.yaml"):
        return "conda"
    if has("Pipfile"):
        return "pipenv"
    return "none"


def _cuda_hints(repo: Path) -> tuple[str, ...]:
    text = _dependency_text(repo)
    snippets: list[str] = []
    rules = (
        ("cupy-cuda", "CuPy CUDA package"),
        ("flash-attn", "flash-attn dependency"),
        ("pytorch-cuda", "pytorch-cuda dependency"),
        ("nvidia-cuda", "NVIDIA CUDA package"),
        ("cuda toolkit", "CUDA toolkit declaration"),
    )
    for needle, label in rules:
        if needle in text:
            snippets.append(label)

    scanned = 0
    for path in repo.rglob("*.py"):
        if scanned >= 120:
            break
        if not _safe_repo_file(repo, path):
            continue
        scanned += 1
        source = _read_text(path, limit=80_000, root=repo).lower()
        if "torch.cuda" in source and "torch.cuda usage" not in snippets:
            snippets.append("torch.cuda usage")
        if re.search(r"\.cuda\s*\(", source) and ".cuda() calls" not in snippets:
            snippets.append(".cuda() calls")
        if len(snippets) >= 8:
            break
    return tuple(snippets)


def _fingerprint(repo: Path, dependency_files: tuple[str, ...], commit_sha: str | None) -> str:
    digest = hashlib.sha256()
    digest.update((commit_sha or "no-commit").encode("utf-8"))
    for name in sorted(dependency_files):
        path = repo / name
        if not _safe_repo_file(repo, path):
            continue
        digest.update(name.encode("utf-8"))
        _hash_file_into(digest, path)
    for name in _MANIFEST_CANDIDATES:
        path = repo / name
        if not _safe_repo_file(repo, path):
            continue
        digest.update(name.encode("utf-8"))
        _hash_file_into(digest, path)
    return digest.hexdigest()


def _warnings(
    repo: Path,
    dependency_files: tuple[str, ...],
    strategy: str,
    suggested_command: str | None,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if not dependency_files:
        warnings.append(
            "No dependency specification was found; environment reconstruction is heuristic."
        )
    if strategy == "conda":
        warnings.append(
            "Conda environment.yml requires a fresh dependency solve; exact rebuilds may drift. "
            "Commit conda-lock.yml/conda-lock.yaml for a lock-bound environment."
        )
    if strategy == "pipenv":
        warnings.append(
            "Pipfile has no Pipfile.lock; dependency resolution may drift. Commit Pipfile.lock for a lock-bound environment."
        )
    if strategy == "requirements":
        lines = [
            line.strip()
            for line in _read_text(repo / "requirements.txt", root=repo).splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "-"))
        ]
        unpinned = [line for line in lines if not re.search(r"(?:==|===|~=|@\s*https?://)", line)]
        if unpinned:
            warnings.append(
                f"requirements.txt contains {len(unpinned)} unpinned direct requirement(s); exact rebuilds may drift."
            )
    if suggested_command is None:
        warnings.append("No safe reproduction entrypoint was detected.")
    return tuple(warnings)


def inspect_repository(repo: Path) -> RepositoryProfile:
    dependency_files = tuple(
        name for name in _DEPENDENCY_CANDIDATES if _safe_repo_file(repo, repo / name)
    )
    manifest = next(
        (repo / name for name in _MANIFEST_CANDIDATES if _safe_repo_file(repo, repo / name)),
        None,
    )
    suggested_command = _suggest_command(repo)
    commit_sha = _git_commit(repo)
    python_requirement, python_source = _python_requirement(repo)
    strategy = _dependency_strategy(repo)
    warnings = _warnings(repo, dependency_files, strategy, suggested_command)
    return RepositoryProfile(
        path=repo,
        stacks=_detect_stacks(repo),
        dependency_files=dependency_files,
        manifest_path=manifest,
        suggested_command=suggested_command,
        commit_sha=commit_sha,
        python_requirement=python_requirement,
        python_source=python_source,
        cuda_hints=_cuda_hints(repo),
        dependency_strategy=strategy,
        fingerprint=_fingerprint(repo, dependency_files, commit_sha),
        warnings=warnings,
    )
