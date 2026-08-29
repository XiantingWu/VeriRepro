from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

import reproagent.experiment as experiment_module
from reproagent.environment import generate_dockerfile
from reproagent.experiment import run_in_docker
from reproagent.repository import inspect_repository

_UNIX_SEMANTICS = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Unix uid/gid/chown semantics are unavailable on Windows",
)


class _Process:
    def __init__(self) -> None:
        self.stdout = io.BytesIO(b"ok\n")
        self.stderr = io.BytesIO(b"")
        self.returncode = 0

    def wait(self, timeout=None):
        del timeout
        return 0

    def kill(self) -> None:
        self.returncode = -9


def _capture(monkeypatch: pytest.MonkeyPatch, commands: list[list[str]]) -> None:
    def fake_popen(command, **kwargs):
        del kwargs
        commands.append(list(command))
        return _Process()

    monkeypatch.setattr(experiment_module.subprocess, "Popen", fake_popen)


@_UNIX_SEMANTICS
def test_runtime_maps_nonroot_host_identity_and_preserves_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []
    _capture(monkeypatch, commands)
    monkeypatch.setattr(experiment_module.os, "getuid", lambda: 1001)
    monkeypatch.setattr(experiment_module.os, "getgid", lambda: 1002)
    run_in_docker("image", "true", tmp_path / "out", tmp_path / "data", timeout=5)
    command = commands[0]
    assert command[command.index("--user") + 1] == "1001:1002"
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--security-opt") + 1] == "no-new-privileges"
    assert command[command.index("--network") + 1] == "none"
    assert "HOME=/tmp" in command


@_UNIX_SEMANTICS
def test_root_host_is_remapped_to_fixed_unprivileged_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []
    chowns: list[tuple[Path, int, int]] = []
    _capture(monkeypatch, commands)
    monkeypatch.setattr(experiment_module.os, "getuid", lambda: 0)
    monkeypatch.setattr(experiment_module.os, "getgid", lambda: 0)
    monkeypatch.setattr(
        experiment_module.os,
        "chown",
        lambda path, uid, gid: chowns.append((Path(path), uid, gid)),
    )
    output = tmp_path / "out"
    run_in_docker("image", "true", output, tmp_path / "data", timeout=5)
    assert chowns == [(output, 65532, 65532)]
    assert commands[0][commands[0].index("--user") + 1] == "65532:65532"


@_UNIX_SEMANTICS
def test_root_host_never_falls_back_to_container_root_when_chown_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(experiment_module.os, "getuid", lambda: 0)
    monkeypatch.setattr(experiment_module.os, "getgid", lambda: 0)
    monkeypatch.setattr(
        experiment_module.os,
        "chown",
        lambda *args: (_ for _ in ()).throw(PermissionError("synthetic")),
    )
    monkeypatch.setattr(
        experiment_module.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Docker must not start")),
    )
    with pytest.raises(RuntimeError, match="refuses container UID 0"):
        run_in_docker("image", "true", tmp_path / "out", tmp_path / "data", timeout=5)


@_UNIX_SEMANTICS
def test_root_group_is_not_carried_into_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []
    _capture(monkeypatch, commands)
    monkeypatch.setattr(experiment_module.os, "getuid", lambda: 1001)
    monkeypatch.setattr(experiment_module.os, "getgid", lambda: 0)
    run_in_docker("image", "true", tmp_path / "out", tmp_path / "data", timeout=5)
    assert commands[0][commands[0].index("--user") + 1] == "1001:1001"


def test_python_dockerfile_seals_repository_template_after_dependency_install(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "python-repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("pytest>=8\n", encoding="utf-8")
    (repo / "reproduce.py").write_text(
        "open('relative-output.txt','w').write('ok')\n", encoding="utf-8"
    )
    profile = inspect_repository(repo)
    dockerfile = generate_dockerfile(profile, repo / "Dockerfile.verirepro", "3.11")
    content = dockerfile.read_text(encoding="utf-8")
    seal = "cp -R /workspace/. /opt/verirepro-repository/"
    assert seal in content
    assert "chmod -R a-w,a+rX /opt/verirepro-repository" in content
    assert "chmod -R a+rwX /workspace" not in content
    assert content.index("COPY . /workspace") < content.index(seal)
    assert content.rindex("python -m pip install") < content.index(seal)


def test_conda_dockerfile_seals_repository_template_after_dependency_install(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "conda-repo"
    repo.mkdir()
    (repo / "environment.yml").write_text(
        "name: demo\ndependencies:\n  - python=3.11\n", encoding="utf-8"
    )
    (repo / "reproduce.py").write_text(
        "open('relative-output.txt','w').write('ok')\n", encoding="utf-8"
    )
    profile = inspect_repository(repo)
    dockerfile = generate_dockerfile(profile, repo / "Dockerfile.verirepro", "3.11")
    content = dockerfile.read_text(encoding="utf-8")
    seal = "cp -R /workspace/. /opt/verirepro-repository/"
    assert seal in content
    assert "chmod -R a-w,a+rX /opt/verirepro-repository" in content
    assert "chmod -R a+rwX /workspace" not in content
    assert content.index("COPY . /workspace") < content.index(seal)
    assert content.index("micromamba install") < content.index(seal)
