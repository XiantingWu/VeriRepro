import subprocess
from pathlib import Path

import pytest

from reproagent.environment import (
    DockerBuildError,
    DockerUnavailableError,
    _docker_hub_mirror_image,
    _dockerfile_base_image,
    _pull_image,
    _resolve_python,
    build_image,
    docker_available,
    generate_dockerfile,
    image_tag,
    plan_environment,
)
from reproagent.models import RepositoryProfile


def _profile(**overrides):
    values = dict(
        path=Path("/tmp/repo"),
        stacks=(),
        dependency_files=("requirements.txt",),
        manifest_path=None,
        suggested_command=None,
        commit_sha="abc123",
        python_requirement=">=3.10,<3.13",
        python_source=None,
        cuda_hints=(),
        dependency_strategy="requirements",
        fingerprint="fingerprint",
        warnings=(),
    )
    values.update(overrides)
    return RepositoryProfile(**values)


def test_environment_plan_selects_supported_python_and_is_deterministic():
    first = plan_environment(_profile())
    second = plan_environment(_profile())
    assert first.python_version in {"3.10", "3.11", "3.12"}
    assert first.environment_fingerprint == second.environment_fingerprint
    assert first.reproducibility_grade == "strong"


def test_environment_plan_marks_unpinned_requirements_medium():
    plan = plan_environment(_profile(warnings=("requirements contain unpinned dependency",)))
    assert plan.reproducibility_grade == "medium"


def test_environment_plan_marks_missing_commit_and_dependencies_weak():
    plan = plan_environment(
        _profile(
            commit_sha=None,
            dependency_files=(),
            dependency_strategy="none",
            fingerprint=None,
            python_requirement=None,
        )
    )
    assert plan.reproducibility_grade == "weak"


def test_environment_plan_surfaces_gpu_diagnostics_without_granting_gpu():
    plan = plan_environment(_profile(cuda_hints=("torch.cuda",)))
    assert plan.gpu_likely is True
    assert any("CUDA/GPU signals" in warning for warning in plan.warnings)


def test_explicit_python_override_wins_and_is_labeled_cli():
    version, source, warnings = _resolve_python(">=3.9", "3.12")
    assert (version, source, warnings) == ("3.12", "cli", [])


def test_explicit_unsupported_python_is_rejected():
    with pytest.raises(ValueError, match="unsupported Python minor"):
        _resolve_python(None, "3.7")


def test_poetry_caret_requirement_uses_repository_minor():
    version, source, warnings = _resolve_python("^3.10", "auto")
    assert version == "3.10"
    assert source == "repository-poetry"
    assert warnings == []


def test_unparseable_repository_requirement_with_minor_uses_heuristic():
    version, source, warnings = _resolve_python("python 3.12 please", "auto")
    assert version == "3.12"
    assert source == "repository-heuristic"
    assert warnings


def test_unparseable_repository_requirement_falls_back_with_warning():
    version, source, warnings = _resolve_python("totally-not-a-spec", "auto")
    assert version == "3.11"
    assert source == "verirepro-default"
    assert warnings


def test_no_supported_repository_minor_falls_back_with_warning():
    version, source, warnings = _resolve_python(">=3.14", "auto")
    assert version == "3.11"
    assert source == "verirepro-default"
    assert any("No supported Python" in warning for warning in warnings)


def test_generate_requirements_dockerfile_preserves_sealed_repository(tmp_path: Path):
    path = generate_dockerfile(_profile(), tmp_path / "Dockerfile", "3.11")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("FROM python:3.11-slim")
    assert "requirements.txt" in text
    assert "/opt/verirepro-repository" in text
    assert "chmod -R a-w,a+rX" in text


def test_generate_dockerfile_adds_scientific_fallback_packages_when_no_dependencies(
    tmp_path: Path,
):
    profile = _profile(
        dependency_files=(),
        dependency_strategy="none",
        stacks=("NumPy", "SciPy", "PyTorch", "Jupyter"),
    )
    path = generate_dockerfile(profile, tmp_path / "Dockerfile", "3.11")
    text = path.read_text(encoding="utf-8")
    assert "python -m pip install numpy scipy torch jupyter nbconvert" in text


def test_generate_uv_dockerfile_uses_frozen_sync_and_venv_path(tmp_path: Path):
    profile = _profile(
        dependency_files=("pyproject.toml", "uv.lock"),
        dependency_strategy="uv",
    )
    text = generate_dockerfile(profile, tmp_path / "Dockerfile", "3.12").read_text(encoding="utf-8")
    assert "uv sync --frozen --no-dev" in text
    assert 'ENV PATH="/workspace/.venv/bin:$PATH"' in text


def test_conda_lock_strategy_requires_lockfile(tmp_path: Path):
    profile = _profile(
        dependency_files=("environment.yml",),
        dependency_strategy="conda-lock",
    )
    with pytest.raises(ValueError, match="requires conda-lock"):
        generate_dockerfile(profile, tmp_path / "Dockerfile", "3.11")


def test_conda_strategy_requires_environment_file(tmp_path: Path):
    profile = _profile(dependency_files=(), dependency_strategy="conda")
    with pytest.raises(ValueError, match="requires environment"):
        generate_dockerfile(profile, tmp_path / "Dockerfile", "3.11")


def test_image_tag_is_deterministic_and_fingerprint_sensitive():
    first = image_tag("https://github.com/example/project", "a")
    assert first == image_tag("https://github.com/example/project", "a")
    assert first != image_tag("https://github.com/example/project", "b")
    assert first.startswith("verirepro-")


def test_dockerfile_base_image_and_mirror_parsing(tmp_path: Path):
    path = tmp_path / "Dockerfile"
    path.write_text("# comment\nFROM python:3.11-slim\nRUN true\n", encoding="utf-8")
    assert _dockerfile_base_image(path) == "python:3.11-slim"
    assert _docker_hub_mirror_image("python:3.11-slim") == "mirror.gcr.io/library/python:3.11-slim"
    assert _docker_hub_mirror_image("ghcr.io/example/image:tag") is None
    path.write_text("FROM scratch\n", encoding="utf-8")
    assert _dockerfile_base_image(path) is None


def test_pull_image_timeout_returns_bounded_failure(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=5, stderr=b"network stalled")

    monkeypatch.setattr("reproagent.environment.subprocess.run", timeout)
    acquired, detail = _pull_image("python:3.11-slim", 5)
    assert acquired is False
    assert "timed out" in detail
    assert "network stalled" in detail


def test_docker_unavailable_when_binary_missing(monkeypatch):
    monkeypatch.setattr("reproagent.environment.shutil.which", lambda _: None)
    assert docker_available() is False


def test_build_image_fails_when_docker_is_unavailable(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("reproagent.environment.docker_available", lambda: False)
    with pytest.raises(DockerUnavailableError, match="Docker is not installed"):
        build_image(tmp_path, tmp_path / "Dockerfile", "verirepro:test", timeout=10)


def test_build_image_surfaces_final_build_tail(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("reproagent.environment.docker_available", lambda: True)
    monkeypatch.setattr(
        "reproagent.environment._ensure_base_image_available",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "reproagent.environment._run_build_bounded",
        lambda *args, **kwargs: (1, "", "line1\nfinal build error"),
    )
    with pytest.raises(DockerBuildError, match="final build error"):
        build_image(tmp_path, tmp_path / "Dockerfile", "verirepro:test", timeout=10)
