from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import BinaryIO

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from .models import EnvironmentPlan, RepositoryProfile


class DockerUnavailableError(RuntimeError):
    pass


class DockerBuildError(DockerUnavailableError):
    """Raised when Docker is reachable but the image cannot be built."""


_SUPPORTED_PYTHON_MINORS = ("3.11", "3.10", "3.12", "3.9", "3.13", "3.8")
_SUPPORTED_PYTHON_SET = frozenset(_SUPPORTED_PYTHON_MINORS)
_DEFAULT_MAX_DOCKER_BUILD_LOG_BYTES = 8 * 1024 * 1024
_BUILD_STREAM_CHUNK_BYTES = 64 * 1024
_BUILD_CLIENT_CLEANUP_SECONDS = 10
_PIPENV_CURRENT_VERSION = "2026.7.1"
_PIPENV_LEGACY_VERSION = "2024.4.1"
_CONDA_LOCK_VERSION = "4.0.2"
_MICROMAMBA_IMAGE = "mambaorg/micromamba:2.9.0-debian13-slim@sha256:b62ed0c54940e3c801642d72ba7d2462f06356c378eba92d603d39f2ce5e4a0d"


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        process = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return process.returncode == 0


def _positive_env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise DockerBuildError(f"{name} must be an integer") from exc
    if value <= 0:
        raise DockerBuildError(f"{name} must be positive")
    return value


def _max_docker_build_log_bytes() -> int:
    return _positive_env_int(
        "VERIREPRO_MAX_DOCKER_BUILD_LOG_BYTES",
        _DEFAULT_MAX_DOCKER_BUILD_LOG_BYTES,
    )


def _validate_python_minor(value: str, *, source: str) -> str:
    candidate = value.strip()
    if candidate not in _SUPPORTED_PYTHON_SET:
        supported = ", ".join(sorted(_SUPPORTED_PYTHON_SET, key=Version))
        raise ValueError(
            f"unsupported Python minor from {source}: {value!r}; supported values are {supported}"
        )
    return candidate


def _exact_minor(requirement: str | None) -> str | None:
    if not requirement:
        return None
    match = re.fullmatch(r"\s*(3\.\d{1,2})(?:\.\d+)?\s*", requirement)
    if match:
        return match.group(1)
    match = re.search(r"(?:==|~=)\s*(3\.\d{1,2})", requirement)
    return match.group(1) if match else None


def _resolve_python(requirement: str | None, requested: str) -> tuple[str, str, list[str]]:
    warnings: list[str] = []
    if requested != "auto":
        return _validate_python_minor(requested, source="CLI/API"), "cli", warnings
    exact = _exact_minor(requirement)
    if exact:
        if exact in _SUPPORTED_PYTHON_SET:
            return exact, "repository", warnings
        warnings.append(
            f"Repository Python requirement {requirement!r} resolves to unsupported minor {exact}; "
            "using 3.11 for planning."
        )
        return "3.11", "verirepro-default", warnings
    if not requirement:
        return "3.11", "verirepro-default", warnings

    normalized = requirement.strip()
    if normalized.startswith("^"):
        match = re.search(r"3\.\d{1,2}", normalized)
        if match and match.group(0) in _SUPPORTED_PYTHON_SET:
            return match.group(0), "repository-poetry", warnings

    try:
        specifier = SpecifierSet(normalized)
    except InvalidSpecifier:
        match = re.search(r"3\.\d{1,2}", normalized)
        if match and match.group(0) in _SUPPORTED_PYTHON_SET:
            warnings.append(
                f"Could not fully parse Python requirement {requirement!r}; using {match.group(0)}."
            )
            return match.group(0), "repository-heuristic", warnings
        warnings.append(
            f"Could not parse supported Python requirement {requirement!r}; using 3.11."
        )
        return "3.11", "verirepro-default", warnings

    for candidate in _SUPPORTED_PYTHON_MINORS:
        if Version(candidate) in specifier:
            return candidate, "repository-specifier", warnings
    warnings.append(
        f"No supported Python 3.8-3.13 minor matches {requirement!r}; using 3.11 for planning."
    )
    return "3.11", "verirepro-default", warnings


def _reproducibility_grade(profile: RepositoryProfile) -> str:
    if profile.commit_sha and profile.dependency_strategy in {
        "uv",
        "poetry",
        "conda-lock",
        "pipenv-lock",
    }:
        return "strong"
    if profile.commit_sha and profile.dependency_strategy == "requirements":
        if not any("unpinned" in warning.lower() for warning in profile.warnings):
            return "strong"
        return "medium"
    if profile.commit_sha and profile.dependency_files:
        return "medium"
    return "weak"


def plan_environment(profile: RepositoryProfile, requested_python: str = "auto") -> EnvironmentPlan:
    python_version, source, resolution_warnings = _resolve_python(
        profile.python_requirement, requested_python
    )
    warnings = list(profile.warnings)
    warnings.extend(resolution_warnings)
    if profile.cuda_hints:
        warnings.append(
            "CUDA/GPU signals were detected. The generic VeriRepro Docker image remains CPU-oriented; "
            "use the plan as a diagnostic until GPU profiles are enabled."
        )

    digest = hashlib.sha256()
    digest.update((profile.fingerprint or "no-repository-fingerprint").encode("utf-8"))
    digest.update(python_version.encode("utf-8"))
    digest.update(profile.dependency_strategy.encode("utf-8"))
    environment_fingerprint = digest.hexdigest()

    return EnvironmentPlan(
        python_version=python_version,
        python_source=(profile.python_source or source) if source != "cli" else "cli",
        python_requirement=profile.python_requirement,
        dependency_strategy=profile.dependency_strategy,
        dependency_files=profile.dependency_files,
        commit_sha=profile.commit_sha,
        repository_fingerprint=profile.fingerprint,
        environment_fingerprint=environment_fingerprint,
        gpu_likely=bool(profile.cuda_hints),
        cuda_hints=profile.cuda_hints,
        reproducibility_grade=_reproducibility_grade(profile),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def write_environment_plan(plan: EnvironmentPlan, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    return destination


def generate_dockerfile(
    profile: RepositoryProfile,
    destination: Path,
    python_version: str = "3.11",
) -> Path:
    python_version = _validate_python_minor(python_version, source="Dockerfile generator")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fallback_packages: list[str] = []
    if not profile.dependency_files:
        if "NumPy" in profile.stacks:
            fallback_packages.append("numpy")
        if "SciPy" in profile.stacks:
            fallback_packages.append("scipy")
        if "PyTorch" in profile.stacks:
            fallback_packages.append("torch")
    if (
        profile.dependency_strategy not in {"uv", "poetry", "conda-lock", "pipenv-lock"}
        and "Jupyter" in profile.stacks
    ):
        fallback_packages.extend(["jupyter", "nbconvert"])

    fallback_line = ""
    if fallback_packages:
        packages = " ".join(dict.fromkeys(fallback_packages))
        fallback_line = f"RUN python -m pip install {packages}\n"

    system_fallback = (
        "apt-get update && apt-get install -y --no-install-recommends git build-essential && "
        "rm -rf /var/lib/apt/lists/*"
    )

    if profile.dependency_strategy in {"conda-lock", "conda"}:
        lock_name = next(
            (
                name
                for name in ("conda-lock.yml", "conda-lock.yaml")
                if name in profile.dependency_files
            ),
            None,
        )
        environment_name = next(
            (
                name
                for name in ("environment.yml", "environment.yaml")
                if name in profile.dependency_files
            ),
            None,
        )
        runtime_env = "base"
        tool_cleanup = ""
        if profile.dependency_strategy == "conda-lock":
            if lock_name is None:
                raise ValueError("conda-lock strategy requires conda-lock.yml or conda-lock.yaml")
            runtime_env = "verirepro"
            dependency_install = (
                "RUN micromamba create -y -p /opt/verirepro-conda-lock-tool -c conda-forge "
                "python=3.11 pip && micromamba clean --all --yes\n"
                f"RUN /opt/verirepro-conda-lock-tool/bin/python -m pip install conda-lock=={_CONDA_LOCK_VERSION}\n"
                "RUN /opt/verirepro-conda-lock-tool/bin/conda-lock install --micromamba "
                f"--name {runtime_env} /workspace/{lock_name} && micromamba clean --all --yes\n"
            )
            tool_cleanup = (
                "USER root\nRUN rm -rf /opt/verirepro-conda-lock-tool\nUSER $MAMBA_USER\n"
            )
        else:
            if environment_name is None:
                raise ValueError("conda strategy requires environment.yml or environment.yaml")
            dependency_install = (
                f"RUN micromamba install -y -n base -f /workspace/{environment_name} && "
                "micromamba clean --all --yes\n"
            )
        conda_fallback = fallback_line.replace(
            "RUN python -m pip install",
            f"RUN micromamba run -n {runtime_env} python -m pip install",
        )
        activation = f"ENV ENV_NAME={runtime_env}\n" if runtime_env != "base" else ""
        content = f"""FROM {_MICROMAMBA_IMAGE}
USER root
WORKDIR /workspace
COPY . /workspace
RUN mkdir -p /repro-output /datasets /opt/verirepro-conda-lock-tool /opt/verirepro-repository && chown -R "$MAMBA_USER":"$MAMBA_USER" /workspace /repro-output /datasets /opt/verirepro-conda-lock-tool /opt/verirepro-repository
USER $MAMBA_USER
{activation}{dependency_install}{tool_cleanup}{conda_fallback}RUN cp -R /workspace/. /opt/verirepro-repository/ && chmod -R a-w,a+rX /opt/verirepro-repository
"""
        destination.write_text(content, encoding="utf-8")
        return destination

    environment_lines = ""
    if profile.dependency_strategy == "uv":
        dependency_install = (
            "RUN python -m pip install uv && "
            f"(uv sync --frozen --no-dev || ({system_fallback} && uv sync --frozen --no-dev))\n"
        )
        environment_lines = 'ENV PATH="/workspace/.venv/bin:$PATH"\n'
    elif profile.dependency_strategy == "poetry":
        poetry_install = (
            "poetry config virtualenvs.create false && "
            "poetry install --only main --no-interaction --no-ansi"
        )
        dependency_install = (
            "RUN python -m pip install poetry && "
            f"({poetry_install} || ({system_fallback} && {poetry_install}))\n"
        )
    elif profile.dependency_strategy in {"pipenv-lock", "pipenv"}:
        pipenv_version = (
            _PIPENV_LEGACY_VERSION
            if Version(python_version) < Version("3.10")
            else _PIPENV_CURRENT_VERSION
        )
        if profile.dependency_strategy == "pipenv-lock":
            pipenv_install = (
                "PIPENV_DONT_LOAD_ENV=1 PIPENV_NOSPIN=1 "
                "pipenv install --system --deploy --ignore-pipfile"
            )
        else:
            pipenv_install = (
                "PIPENV_DONT_LOAD_ENV=1 PIPENV_NOSPIN=1 pipenv install --system --skip-lock"
            )
        dependency_install = (
            f"RUN python -m pip install pipenv=={pipenv_version} && "
            f"({pipenv_install} || ({system_fallback} && {pipenv_install}))\n"
        )
    else:
        dependency_install = f"""RUN if [ -f requirements.txt ]; then \\
        python -m pip install --only-binary=:all: -r requirements.txt || ({system_fallback} && python -m pip install -r requirements.txt); \\
    elif [ -f pyproject.toml ]; then \\
        python -m pip install . || ({system_fallback} && python -m pip install .); \\
    elif [ -f setup.py ]; then \\
        python -m pip install . || ({system_fallback} && python -m pip install .); \\
    fi
"""

    content = f"""FROM python:{python_version}-slim
ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace
COPY . /workspace
RUN python -m pip install --upgrade pip setuptools wheel
{dependency_install}{environment_lines}{fallback_line}RUN mkdir -p /opt/verirepro-repository /repro-output /datasets && cp -R /workspace/. /opt/verirepro-repository/ && chmod -R a-w,a+rX /opt/verirepro-repository
"""
    destination.write_text(content, encoding="utf-8")
    return destination


def image_tag(repository_url: str, fingerprint: str | None = None) -> str:
    seed = f"{repository_url}|{fingerprint or ''}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"verirepro-{digest}"


def _build_output_tail(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    def text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value

    combined = text(stderr) or text(stdout)
    return "\n".join(combined.splitlines()[-40:])


def _drain_tail_bounded(stream: BinaryIO, limit: int, sink: list[tuple[bytes, int]]) -> None:
    retained = bytearray()
    total = 0
    try:
        while True:
            chunk = stream.read(_BUILD_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            retained.extend(chunk)
            if len(retained) > limit:
                del retained[: len(retained) - limit]
    finally:
        try:
            stream.close()
        except OSError:
            pass
    sink.append((bytes(retained), total))


def _bounded_build_text(capture: list[tuple[bytes, int]], limit: int) -> str:
    if not capture:
        return ""
    payload, total = capture[0]
    text = payload.decode("utf-8", errors="replace")
    if total > limit:
        return f"[VeriRepro Docker build log truncated to final {limit} of {total} bytes]\n{text}"
    return text


def _stop_build_client(process: subprocess.Popen[bytes]) -> None:
    try:
        process.kill()
    except OSError:
        return
    try:
        process.wait(timeout=_BUILD_CLIENT_CLEANUP_SECONDS)
    except subprocess.TimeoutExpired:
        return


def _run_build_bounded(command: list[str], timeout: int) -> tuple[int, str, str]:
    if timeout <= 0:
        raise DockerBuildError("Docker build timeout must be positive")
    limit = _max_docker_build_log_bytes()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_capture: list[tuple[bytes, int]] = []
    stderr_capture: list[tuple[bytes, int]] = []
    stdout_thread = threading.Thread(
        target=_drain_tail_bounded,
        args=(process.stdout, limit, stdout_capture),
        name="verirepro-docker-build-stdout",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_tail_bounded,
        args=(process.stderr, limit, stderr_capture),
        name="verirepro-docker-build-stderr",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _stop_build_client(process)
        stdout_thread.join(timeout=_BUILD_CLIENT_CLEANUP_SECONDS)
        stderr_thread.join(timeout=_BUILD_CLIENT_CLEANUP_SECONDS)
        stdout = _bounded_build_text(stdout_capture, limit)
        stderr = _bounded_build_text(stderr_capture, limit)
        tail = _build_output_tail(stdout, stderr)
        detail = f"\n{tail}" if tail else ""
        raise DockerBuildError(
            f"Docker build timed out after {timeout} seconds{detail}. "
            "The Docker client was stopped; for hostile repositories use an isolated builder/VM because daemon-side build cancellation is runtime-dependent."
        ) from exc

    stdout_thread.join(timeout=_BUILD_CLIENT_CLEANUP_SECONDS)
    stderr_thread.join(timeout=_BUILD_CLIENT_CLEANUP_SECONDS)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        _stop_build_client(process)
        raise DockerBuildError("Docker build log capture did not terminate cleanly")
    return (
        int(process.returncode or 0),
        _bounded_build_text(stdout_capture, limit),
        _bounded_build_text(stderr_capture, limit),
    )


def _dockerfile_base_image(dockerfile: Path) -> str | None:
    for raw_line in dockerfile.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.upper().startswith("FROM "):
            return None
        parts = line.split()
        if len(parts) < 2:
            return None
        image = parts[1]
        return None if image.lower() == "scratch" else image
    return None


def _docker_hub_mirror_image(base_image: str) -> str | None:
    if "/" in base_image or "@" in base_image:
        return None
    return f"mirror.gcr.io/library/{base_image}"


def _pull_image(image: str, timeout: int) -> tuple[bool, str]:
    try:
        pull = subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        tail = _build_output_tail(exc.stdout, exc.stderr)
        return False, f"pull timed out after {timeout} seconds" + (f"\n{tail}" if tail else "")
    if pull.returncode != 0:
        tail = _build_output_tail(pull.stdout, pull.stderr)
        return False, "pull failed" + (f"\n{tail}" if tail else "")
    return True, ""


def _ensure_base_image_available(dockerfile: Path, timeout: int) -> None:
    base_image = _dockerfile_base_image(dockerfile)
    if not base_image:
        return

    try:
        inspect = subprocess.run(
            ["docker", "image", "inspect", base_image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=min(15, timeout),
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        inspect = None
    if inspect is not None and inspect.returncode == 0:
        return

    pull_timeout = min(120, max(15, timeout // 4))
    acquired, canonical_error = _pull_image(base_image, pull_timeout)
    if acquired:
        return

    mirror_image = _docker_hub_mirror_image(base_image) if timeout >= 300 else None
    if mirror_image:
        acquired, mirror_error = _pull_image(mirror_image, pull_timeout)
        if acquired:
            try:
                tag = subprocess.run(
                    ["docker", "tag", mirror_image, base_image],
                    capture_output=True,
                    text=True,
                    timeout=min(30, timeout),
                    check=False,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                raise DockerBuildError(
                    f"Docker base image {base_image!r} was acquired from {mirror_image!r} "
                    f"but could not be retagged: {exc}"
                ) from exc
            if tag.returncode == 0:
                return
            tail = _build_output_tail(tag.stdout, tag.stderr)
            detail = f"\n{tail}" if tail else ""
            raise DockerBuildError(
                f"Docker base image {base_image!r} was acquired from {mirror_image!r} but could not be retagged{detail}"
            )
        raise DockerBuildError(
            f"Docker base image {base_image!r} could not be acquired from Docker Hub ({canonical_error}) "
            f"or its public mirror {mirror_image!r} ({mirror_error})"
        )

    raise DockerBuildError(
        f"Docker base image {base_image!r} could not be acquired: {canonical_error}"
    )


def build_image(repo: Path, dockerfile: Path, tag: str, timeout: int = 1800) -> None:
    if not docker_available():
        raise DockerUnavailableError("Docker is not installed or the Docker daemon is unavailable")
    _ensure_base_image_available(dockerfile, timeout)
    command = ["docker", "build", "--pull=false", "-f", str(dockerfile), "-t", tag, str(repo)]
    return_code, stdout, stderr = _run_build_bounded(command, timeout)
    if return_code != 0:
        tail = _build_output_tail(stdout, stderr)
        detail = f"\n{tail}" if tail else ""
        raise DockerBuildError(f"Docker build failed{detail}")
