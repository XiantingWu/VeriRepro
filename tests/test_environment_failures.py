"""Failure-path coverage for reproagent.environment (all docker interactions faked)."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from reproagent.environment import (
    DockerBuildError,
    DockerUnavailableError,
    _bounded_build_text,
    _build_output_tail,
    _dockerfile_base_image,
    _drain_tail_bounded,
    _ensure_base_image_available,
    _exact_minor,
    _max_docker_build_log_bytes,
    _positive_env_int,
    _pull_image,
    _resolve_python,
    _run_build_bounded,
    _stop_build_client,
    build_image,
    docker_available,
    generate_dockerfile,
    plan_environment,
    write_environment_plan,
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


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class _FakeBuildProcess:
    """Minimal subprocess.Popen stand-in with pipe-like byte streams."""

    def __init__(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        wait_effects: tuple[object, ...] | None = None,
    ) -> None:
        self.stdout: io.BytesIO = io.BytesIO(stdout)
        self.stderr: io.BytesIO = io.BytesIO(stderr)
        self.returncode = returncode
        self.killed = False
        self.wait_calls = 0
        self.wait_effects = wait_effects or ()

    def wait(self, timeout=None) -> int:
        del timeout
        index = min(self.wait_calls, len(self.wait_effects) - 1)
        effect = self.wait_effects[index] if self.wait_effects else None
        self.wait_calls += 1
        if isinstance(effect, Exception):
            raise effect
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def _patch_popen(monkeypatch, process: _FakeBuildProcess) -> list[list[str]]:
    commands: list[list[str]] = []

    def fake_popen(command, **kwargs):
        del kwargs
        commands.append(list(command))
        return process

    monkeypatch.setattr("reproagent.environment.subprocess.Popen", fake_popen)
    return commands


# --- docker_available -------------------------------------------------------


def test_docker_available_true_when_server_probe_succeeds(monkeypatch):
    monkeypatch.setattr("reproagent.environment.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(
        "reproagent.environment.subprocess.run",
        lambda *args, **kwargs: _completed(0),
    )
    assert docker_available() is True


def test_docker_available_false_when_daemon_reports_error(monkeypatch):
    monkeypatch.setattr("reproagent.environment.shutil.which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(
        "reproagent.environment.subprocess.run",
        lambda *args, **kwargs: _completed(1),
    )
    assert docker_available() is False


def test_docker_available_false_when_binary_exec_raises_oserror(monkeypatch):
    monkeypatch.setattr("reproagent.environment.shutil.which", lambda _: "/usr/bin/docker")

    def explode(*args, **kwargs):
        raise OSError("exec format error")

    monkeypatch.setattr("reproagent.environment.subprocess.run", explode)
    assert docker_available() is False


def test_docker_available_false_when_server_probe_times_out(monkeypatch):
    monkeypatch.setattr("reproagent.environment.shutil.which", lambda _: "/usr/bin/docker")

    def stall(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["docker"], timeout=15)

    monkeypatch.setattr("reproagent.environment.subprocess.run", stall)
    assert docker_available() is False


def test_build_image_wraps_missing_daemon_as_typed_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("reproagent.environment.shutil.which", lambda _: None)
    with pytest.raises(DockerUnavailableError, match="daemon is unavailable"):
        build_image(tmp_path, tmp_path / "Dockerfile", "verirepro:test", timeout=10)


# --- tunables ---------------------------------------------------------------


def test_max_build_log_bytes_defaults_to_eight_mebibytes(monkeypatch):
    monkeypatch.delenv("VERIREPRO_MAX_DOCKER_BUILD_LOG_BYTES", raising=False)
    assert _max_docker_build_log_bytes() == 8 * 1024 * 1024


@pytest.mark.parametrize("raw", ["abc", "3.5", "1e3"])
def test_positive_env_int_rejects_non_integers(monkeypatch, raw):
    monkeypatch.setenv("VERIREPRO_MAX_DOCKER_BUILD_LOG_BYTES", raw)
    with pytest.raises(DockerBuildError, match="must be an integer"):
        _positive_env_int("VERIREPRO_MAX_DOCKER_BUILD_LOG_BYTES", 8)


def test_positive_env_int_treats_blank_as_default(monkeypatch):
    monkeypatch.setenv("VERIREPRO_MAX_DOCKER_BUILD_LOG_BYTES", "   ")
    assert _positive_env_int("VERIREPRO_MAX_DOCKER_BUILD_LOG_BYTES", 42) == 42


@pytest.mark.parametrize("raw", ["0", "-4"])
def test_positive_env_int_rejects_non_positive_values(monkeypatch, raw):
    monkeypatch.setenv("VERIREPRO_MAX_DOCKER_BUILD_LOG_BYTES", raw)
    with pytest.raises(DockerBuildError, match="must be positive"):
        _max_docker_build_log_bytes()


def test_positive_env_int_accepts_configured_value(monkeypatch):
    monkeypatch.setenv("VERIREPRO_MAX_DOCKER_BUILD_LOG_BYTES", "128")
    assert _max_docker_build_log_bytes() == 128


# --- python requirement resolution ------------------------------------------


def test_exact_minor_matches_bare_pinned_and_range_forms():
    assert _exact_minor("3.12") == "3.12"
    assert _exact_minor("  3.13 ") == "3.13"
    assert _exact_minor("==3.12.4") == "3.12"
    assert _exact_minor("~= 3.9") == "3.9"
    assert _exact_minor(">=3.10,<3.13") is None
    assert _exact_minor(None) is None


def test_resolve_python_uses_supported_exact_repository_minor():
    assert _resolve_python("3.11", "auto") == ("3.11", "repository", [])


def test_resolve_python_warns_when_exact_minor_is_unsupported():
    version, source, warnings = _resolve_python("3.14", "auto")
    assert version == "3.11"
    assert source == "verirepro-default"
    assert any("resolves to unsupported minor 3.14" in warning for warning in warnings)


def test_resolve_python_caret_unsupported_minor_falls_back_to_default():
    version, source, warnings = _resolve_python("^3.14", "auto")
    assert version == "3.11"
    assert source == "verirepro-default"
    assert any("Could not parse supported Python requirement" in warning for warning in warnings)


def test_plan_environment_rejects_unsupported_explicit_python():
    with pytest.raises(ValueError, match="unsupported Python minor"):
        plan_environment(_profile(), requested_python="3.99")


# --- capability classification ----------------------------------------------


def test_grade_medium_for_commit_and_files_but_no_lock_strategy():
    plan = plan_environment(_profile(dependency_strategy="none"))
    assert plan.reproducibility_grade == "medium"


def test_plan_environment_prefers_profile_python_source_over_internal_label():
    plan = plan_environment(_profile(python_source="pyproject.toml"))
    assert plan.python_version == "3.11"
    assert plan.python_source == "pyproject.toml"


def test_plan_environment_labels_cli_override_as_cli():
    plan = plan_environment(_profile(), requested_python="3.12")
    assert plan.python_version == "3.12"
    assert plan.python_source == "cli"


def test_plan_environment_deduplicates_warnings():
    plan = plan_environment(_profile(warnings=("dup", "dup")))
    assert plan.warnings == ("dup",)


def test_plan_environment_fingerprint_tracks_strategy_and_tolerates_missing_id():
    baseline = plan_environment(_profile())
    other = plan_environment(_profile(dependency_strategy="uv"))
    anonymous = plan_environment(_profile(fingerprint=None))
    assert baseline.environment_fingerprint != other.environment_fingerprint
    assert anonymous.repository_fingerprint is None
    assert len(anonymous.environment_fingerprint) == 64


def test_write_environment_plan_creates_parents_and_round_trips(tmp_path: Path):
    destination = tmp_path / "nested" / "dir" / "plan.json"
    plan = plan_environment(_profile())
    assert write_environment_plan(plan, destination) == destination
    restored = json.loads(destination.read_text(encoding="utf-8"))
    assert restored["python_version"] == plan.python_version
    assert restored["environment_fingerprint"] == plan.environment_fingerprint


def test_gpu_hints_stay_diagnostic_and_image_remains_cpu_only(tmp_path: Path):
    profile = _profile(cuda_hints=("torch.cuda.is_available",), stacks=("PyTorch",))
    plan = plan_environment(profile)
    text = generate_dockerfile(profile, tmp_path / "Dockerfile", plan.python_version).read_text(
        encoding="utf-8"
    )
    assert plan.gpu_likely is True
    assert any("CPU-oriented" in warning for warning in plan.warnings)
    lowered = text.lower()
    assert "--gpus" not in lowered
    assert "nvidia" not in lowered
    assert text.startswith("FROM python:3.11-slim")


# --- Dockerfile generation strategies ---------------------------------------


def test_conda_lock_dockerfile_pins_tool_and_seals_runtime(tmp_path: Path):
    profile = _profile(
        dependency_files=("conda-lock.yml",),
        dependency_strategy="conda-lock",
    )
    text = generate_dockerfile(profile, tmp_path / "Dockerfile", "3.11").read_text(encoding="utf-8")
    assert text.startswith("FROM mambaorg/micromamba:")
    assert "@sha256:" in text.splitlines()[0]
    assert "pip install conda-lock==4.0.2" in text
    assert "conda-lock install --micromamba --name verirepro /workspace/conda-lock.yml" in text
    assert "rm -rf /opt/verirepro-conda-lock-tool" in text
    assert "ENV ENV_NAME=verirepro" in text


def test_conda_dockerfile_installs_environment_yaml_into_base(tmp_path: Path):
    profile = _profile(
        dependency_files=("environment.yaml",),
        dependency_strategy="conda",
        stacks=("Jupyter",),
    )
    text = generate_dockerfile(profile, tmp_path / "Dockerfile", "3.11").read_text(encoding="utf-8")
    assert "micromamba install -y -n base -f /workspace/environment.yaml" in text
    assert "micromamba run -n base python -m pip install jupyter nbconvert" in text
    assert "ENV ENV_NAME" not in text


def test_poetry_dockerfile_installs_main_group_only(tmp_path: Path):
    profile = _profile(
        dependency_files=("pyproject.toml", "poetry.lock"),
        dependency_strategy="poetry",
    )
    text = generate_dockerfile(profile, tmp_path / "Dockerfile", "3.11").read_text(encoding="utf-8")
    assert "pip install poetry" in text
    assert "poetry config virtualenvs.create false" in text
    assert "poetry install --only main --no-interaction --no-ansi" in text


def test_pipenv_lock_pins_legacy_pipenv_before_py310(tmp_path: Path):
    profile = _profile(
        dependency_files=("Pipfile.lock",),
        dependency_strategy="pipenv-lock",
    )
    text = generate_dockerfile(profile, tmp_path / "Dockerfile", "3.9").read_text(encoding="utf-8")
    assert "pipenv==2024.4.1" in text
    assert "pipenv install --system --deploy --ignore-pipfile" in text


def test_plain_pipenv_skips_lock_on_current_python(tmp_path: Path):
    profile = _profile(
        dependency_files=("Pipfile",),
        dependency_strategy="pipenv",
    )
    text = generate_dockerfile(profile, tmp_path / "Dockerfile", "3.11").read_text(encoding="utf-8")
    assert "pipenv==2026.7.1" in text
    assert "pipenv install --system --skip-lock" in text


def test_generate_dockerfile_validates_requested_minor(tmp_path: Path):
    with pytest.raises(ValueError, match="unsupported Python minor"):
        generate_dockerfile(_profile(), tmp_path / "Dockerfile", "3.14")


# --- build output helpers ----------------------------------------------------


def test_build_output_tail_decodes_bytes_and_prefers_stderr():
    assert _build_output_tail(b"step 1/4\nstep 2/4", None) == "step 1/4\nstep 2/4"
    assert _build_output_tail("stdout noise", "stderr error") == "stderr error"
    assert _build_output_tail("stdout noise", "") == "stdout noise"
    assert _build_output_tail(None, None) == ""


def test_build_output_tail_keeps_last_forty_lines():
    payload = "\n".join(f"line-{index}" for index in range(50))
    kept = _build_output_tail(payload, "").splitlines()
    assert kept[0] == "line-10"
    assert kept[-1] == "line-49"
    assert len(kept) == 40


class _CloseFailingStream(io.BytesIO):
    def close(self) -> None:
        super().close()
        raise OSError("close failed")


def test_drain_tail_bounded_retains_final_bytes_and_closes_stream():
    stream = io.BytesIO(b"x" * 300)
    sink: list[tuple[bytes, int]] = []
    _drain_tail_bounded(stream, 100, sink)
    assert sink == [(b"x" * 100, 300)]
    assert stream.closed is True


def test_drain_tail_bounded_swallows_close_errors():
    stream = _CloseFailingStream(b"data")
    sink: list[tuple[bytes, int]] = []
    _drain_tail_bounded(stream, 10, sink)
    assert sink == [(b"data", 4)]


def test_bounded_build_text_handles_empty_capture():
    assert _bounded_build_text([], 100) == ""


def test_bounded_build_text_marks_truncation_when_total_exceeds_limit():
    capture: list[tuple[bytes, int]] = []
    stream = io.BytesIO(b"x" * 64)
    _drain_tail_bounded(stream, 16, capture)
    text = _bounded_build_text(capture, 16)
    assert text.startswith("[VeriRepro Docker build log truncated to final 16 of 64 bytes]")
    assert text.endswith("x" * 16)


# --- build client lifecycle --------------------------------------------------


def test_stop_build_client_tolerates_kill_failure():
    class _Unkillable(_FakeBuildProcess):
        def kill(self) -> None:
            raise OSError("process already reaped")

    process = _Unkillable()
    _stop_build_client(process)  # type: ignore[arg-type]
    assert process.wait_calls == 0


def test_stop_build_client_tolerates_post_kill_wait_timeout():
    process = _FakeBuildProcess(
        wait_effects=(subprocess.TimeoutExpired(cmd=["docker"], timeout=10),)
    )
    _stop_build_client(process)
    assert process.killed is True
    assert process.wait_calls == 1


# --- bounded build execution -------------------------------------------------


def test_run_build_bounded_rejects_non_positive_timeout(tmp_path: Path):
    with pytest.raises(DockerBuildError, match="timeout must be positive"):
        _run_build_bounded(["docker", "build"], 0)


def test_run_build_bounded_returns_decoded_streams_on_success(monkeypatch):
    process = _FakeBuildProcess(stdout=b"built\n", stderr=b"", returncode=0)
    _patch_popen(monkeypatch, process)
    return_code, stdout, stderr = _run_build_bounded(["docker", "build"], 60)
    assert (return_code, stdout, stderr) == (0, "built\n", "")


def test_run_build_bounded_propagates_nonzero_returncode(monkeypatch):
    process = _FakeBuildProcess(stdout=b"", stderr=b"apt-get failed\n", returncode=7)
    _patch_popen(monkeypatch, process)
    return_code, _, stderr = _run_build_bounded(["docker", "build"], 60)
    assert return_code == 7
    assert "apt-get failed" in stderr


def test_run_build_bounded_raises_typed_timeout_and_stops_client(monkeypatch):
    process = _FakeBuildProcess(
        stdout=b"Step 3/10\n",
        stderr=b"",
        returncode=137,
        wait_effects=(subprocess.TimeoutExpired(cmd=["docker", "build"], timeout=2),),
    )
    _patch_popen(monkeypatch, process)
    with pytest.raises(DockerBuildError) as excinfo:
        _run_build_bounded(["docker", "build"], 2)
    message = str(excinfo.value)
    assert "timed out after 2 seconds" in message
    assert "Step 3/10" in message
    assert "isolated builder/VM" in message
    assert process.killed is True


def test_run_build_bounded_truncates_oversized_logs(monkeypatch):
    monkeypatch.setenv("VERIREPRO_MAX_DOCKER_BUILD_LOG_BYTES", "16")
    process = _FakeBuildProcess(stdout=b"x" * 100, stderr=b"", returncode=0)
    _patch_popen(monkeypatch, process)
    _, stdout, _ = _run_build_bounded(["docker", "build"], 60)
    assert "[VeriRepro Docker build log truncated to final 16 of 100 bytes]" in stdout


# --- base image parsing ------------------------------------------------------


def test_base_image_returns_none_for_non_from_first_directive(tmp_path: Path):
    path = tmp_path / "Dockerfile"
    path.write_text("ARG BASE=python:3.11-slim\nRUN true\n", encoding="utf-8")
    assert _dockerfile_base_image(path) is None


def test_base_image_handles_bare_from_and_empty_file(tmp_path: Path):
    bare = tmp_path / "bare"
    bare.write_text("# only comments\nFROM\n", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.write_text("", encoding="utf-8")
    assert _dockerfile_base_image(bare) is None
    assert _dockerfile_base_image(empty) is None


# --- image pull --------------------------------------------------------------


def test_pull_image_success_reports_acquired(monkeypatch):
    monkeypatch.setattr(
        "reproagent.environment.subprocess.run",
        lambda *args, **kwargs: _completed(0),
    )
    assert _pull_image("python:3.11-slim", 30) == (True, "")


def test_pull_image_failure_includes_registry_tail(monkeypatch):
    monkeypatch.setattr(
        "reproagent.environment.subprocess.run",
        lambda *args, **kwargs: _completed(1, stderr="toomanyrequests: rate limited"),
    )
    acquired, detail = _pull_image("python:3.11-slim", 30)
    assert acquired is False
    assert detail.startswith("pull failed")
    assert "toomanyrequests" in detail


# --- base image acquisition --------------------------------------------------


def test_existing_base_image_skips_pull_entirely(tmp_path: Path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        del kwargs
        calls.append(list(command))
        return _completed(0)

    monkeypatch.setattr("reproagent.environment.subprocess.run", fake_run)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n", encoding="utf-8")
    _ensure_base_image_available(dockerfile, 600)
    assert calls == [["docker", "image", "inspect", "python:3.11-slim"]]


def test_missing_base_image_is_pulled_from_docker_hub(tmp_path: Path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        del kwargs
        calls.append(list(command))
        return _completed(0 if command[1] == "pull" else 1)

    monkeypatch.setattr("reproagent.environment.subprocess.run", fake_run)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n", encoding="utf-8")
    _ensure_base_image_available(dockerfile, 600)
    assert calls[0][1] == "image"
    assert calls[1] == ["docker", "pull", "python:3.11-slim"]
    assert len(calls) == 2


def test_base_image_without_mirror_window_raises_canonical_error(tmp_path: Path, monkeypatch):
    def fake_run(command, **kwargs):
        del kwargs
        return _completed(1, stderr="dial tcp: connection refused")

    monkeypatch.setattr("reproagent.environment.subprocess.run", fake_run)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n", encoding="utf-8")
    with pytest.raises(DockerBuildError, match="could not be acquired") as excinfo:
        _ensure_base_image_available(dockerfile, 120)
    assert "connection refused" in str(excinfo.value)


def test_base_image_reports_both_hub_and_mirror_failures(tmp_path: Path, monkeypatch):
    def fake_run(command, **kwargs):
        del kwargs
        if command[1:3] == ["image", "inspect"]:
            return _completed(1)
        return _completed(1, stderr=f"no such image: {command[-1]}")

    monkeypatch.setattr("reproagent.environment.subprocess.run", fake_run)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n", encoding="utf-8")
    with pytest.raises(DockerBuildError) as excinfo:
        _ensure_base_image_available(dockerfile, 600)
    message = str(excinfo.value)
    assert "Docker Hub" in message
    assert "mirror.gcr.io/library/python:3.11-slim" in message


def test_mirror_acquisition_retag_failure_is_typed(tmp_path: Path, monkeypatch):
    def fake_run(command, **kwargs):
        del kwargs
        if command[1:3] == ["image", "inspect"]:
            return _completed(1)
        if command[1] == "tag":
            return _completed(1, stderr="tag denied")
        return _completed(0 if command[-1].startswith("mirror.") else 1)

    monkeypatch.setattr("reproagent.environment.subprocess.run", fake_run)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n", encoding="utf-8")
    with pytest.raises(DockerBuildError, match="could not be retagged") as excinfo:
        _ensure_base_image_available(dockerfile, 600)
    assert "tag denied" in str(excinfo.value)


def test_mirror_fallback_retags_base_image_successfully(tmp_path: Path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        del kwargs
        calls.append(list(command))
        if command[1:3] == ["image", "inspect"]:
            return _completed(1)
        if command[1] == "pull":
            return _completed(0 if command[-1].startswith("mirror.") else 1)
        return _completed(0)

    monkeypatch.setattr("reproagent.environment.subprocess.run", fake_run)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n", encoding="utf-8")
    _ensure_base_image_available(dockerfile, 600)
    assert calls[-1] == [
        "docker",
        "tag",
        "mirror.gcr.io/library/python:3.11-slim",
        "python:3.11-slim",
    ]


def test_scratch_base_image_needs_no_acquisition(tmp_path: Path, monkeypatch):
    def fail_run(*args, **kwargs):
        raise AssertionError("no docker calls expected for scratch images")

    monkeypatch.setattr("reproagent.environment.subprocess.run", fail_run)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM scratch\nCOPY . /workspace\n", encoding="utf-8")
    assert _ensure_base_image_available(dockerfile, 600) is None


# --- build_image orchestration -----------------------------------------------


def test_build_image_succeeds_and_passes_expected_command(tmp_path: Path, monkeypatch):
    seen: dict[str, object] = {}

    def fake_run_bounded(command, timeout):
        seen["command"] = list(command)
        seen["timeout"] = timeout
        return 0, "", ""

    monkeypatch.setattr("reproagent.environment.docker_available", lambda: True)
    monkeypatch.setattr("reproagent.environment._ensure_base_image_available", lambda *_: None)
    monkeypatch.setattr("reproagent.environment._run_build_bounded", fake_run_bounded)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n", encoding="utf-8")
    assert build_image(tmp_path, dockerfile, "verirepro:test", timeout=90) is None
    assert seen["command"] == [
        "docker",
        "build",
        "--pull=false",
        "-f",
        str(dockerfile),
        "-t",
        "verirepro:test",
        str(tmp_path),
    ]
    assert seen["timeout"] == 90


def test_build_image_surfaces_build_log_tail_on_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("reproagent.environment.docker_available", lambda: True)
    monkeypatch.setattr("reproagent.environment._ensure_base_image_available", lambda *_: None)

    def failing_build(command, timeout):
        del command, timeout
        return 1, "Step 2/5 : RUN pip install\n", "ERROR: ResolutionImpossible\n"

    monkeypatch.setattr("reproagent.environment._run_build_bounded", failing_build)
    with pytest.raises(DockerBuildError) as excinfo:
        build_image(tmp_path, tmp_path / "Dockerfile", "verirepro:test", timeout=10)
    message = str(excinfo.value)
    assert message.startswith("Docker build failed")
    assert "ResolutionImpossible" in message


def test_docker_build_error_specializes_unavailable_error():
    assert issubclass(DockerBuildError, DockerUnavailableError)


def test_inspect_timeout_falls_through_to_pull_path(tmp_path: Path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        del kwargs
        calls.append(list(command))
        if command[1] == "image":
            raise subprocess.TimeoutExpired(cmd=command, timeout=15)
        return _completed(0)

    monkeypatch.setattr("reproagent.environment.subprocess.run", fake_run)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n", encoding="utf-8")
    _ensure_base_image_available(dockerfile, 600)
    assert calls[0][1] == "image"
    assert calls[1] == ["docker", "pull", "python:3.11-slim"]


def test_mirror_retag_timeout_raises_typed_error(tmp_path: Path, monkeypatch):
    def fake_run(command, **kwargs):
        del kwargs
        if command[1] == "image":
            return _completed(1)
        if command[1] == "pull":
            if command[2].startswith("python:"):
                return _completed(1, stderr="toomanyrequests")
            return _completed(0)
        raise subprocess.TimeoutExpired(cmd=command, timeout=30)

    monkeypatch.setattr("reproagent.environment.subprocess.run", fake_run)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11-slim\n", encoding="utf-8")
    with pytest.raises(DockerBuildError, match="could not be retagged") as excinfo:
        _ensure_base_image_available(dockerfile, 600)
    assert "retagged" in str(excinfo.value)
