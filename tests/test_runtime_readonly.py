from __future__ import annotations

import io
from pathlib import Path

import pytest

import reproagent.experiment as experiment_module
from reproagent.environment import generate_dockerfile
from reproagent.experiment import run_in_docker
from reproagent.repository import inspect_repository


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


def test_runtime_is_read_only_with_owned_workspace_and_tmp_tmpfs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []
    _capture(monkeypatch, commands)
    monkeypatch.setattr(experiment_module.os, "getuid", lambda: 1001)
    monkeypatch.setattr(experiment_module.os, "getgid", lambda: 1002)
    monkeypatch.setenv("VERIREPRO_RUNTIME_WORKSPACE_TMPFS_BYTES", "123456")
    monkeypatch.setenv("VERIREPRO_RUNTIME_TMP_TMPFS_BYTES", "654321")
    run_in_docker("image", "python reproduce.py", tmp_path / "out", tmp_path / "data", timeout=5)
    command = commands[0]
    assert "--read-only" in command
    tmpfs_values = [command[index + 1] for index, value in enumerate(command) if value == "--tmpfs"]
    assert "/workspace:rw,nosuid,nodev,exec,size=123456,mode=0700,uid=1001,gid=1002" in tmpfs_values
    assert "/tmp:rw,nosuid,nodev,exec,size=654321,mode=0700,uid=1001,gid=1002" in tmpfs_values
    assert "TMPDIR=/tmp" in command
    assert "XDG_CACHE_HOME=/tmp/.cache" in command
    assert "MPLCONFIGDIR=/tmp/matplotlib" in command
    assert command[-5:] == [
        "sh",
        "-lc",
        experiment_module._RUNTIME_BOOTSTRAP,
        "verirepro-runtime",
        "python reproduce.py",
    ]


def test_runtime_bootstrap_makes_only_ephemeral_workspace_owner_writable() -> None:
    assert "cp -R /opt/verirepro-repository/. /workspace/" in experiment_module._RUNTIME_BOOTSTRAP
    assert "chmod -R u+rwX /workspace" in experiment_module._RUNTIME_BOOTSTRAP
    assert "chmod -R a+rwX /workspace" not in experiment_module._RUNTIME_BOOTSTRAP
    assert (
        "chmod"
        not in experiment_module._RUNTIME_BOOTSTRAP.split(
            "cp -R /opt/verirepro-repository/. /workspace/;"
        )[0]
    )


def test_invalid_runtime_tmpfs_budget_fails_before_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERIREPRO_RUNTIME_WORKSPACE_TMPFS_BYTES", "0")
    monkeypatch.setattr(
        experiment_module.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Docker must not start")),
    )
    with pytest.raises(RuntimeError, match="must be positive"):
        run_in_docker("image", "true", tmp_path / "out", tmp_path / "data", timeout=5)


def test_python_image_contains_sealed_runtime_repository_template(tmp_path: Path) -> None:
    repo = tmp_path / "python-repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("pytest>=8\n", encoding="utf-8")
    (repo / "reproduce.py").write_text("print('ok')\n", encoding="utf-8")
    profile = inspect_repository(repo)
    dockerfile = generate_dockerfile(profile, repo / "Dockerfile.verirepro", "3.11")
    content = dockerfile.read_text(encoding="utf-8")
    seal = "cp -R /workspace/. /opt/verirepro-repository/"
    assert seal in content
    assert content.index("COPY . /workspace") < content.index(seal)
    assert content.rindex("python -m pip install") < content.index(seal)
    assert "chmod -R a-w,a+rX /opt/verirepro-repository" in content


def test_conda_image_contains_sealed_runtime_repository_template(tmp_path: Path) -> None:
    repo = tmp_path / "conda-repo"
    repo.mkdir()
    (repo / "environment.yml").write_text(
        "name: demo\ndependencies:\n  - python=3.11\n", encoding="utf-8"
    )
    (repo / "reproduce.py").write_text("print('ok')\n", encoding="utf-8")
    profile = inspect_repository(repo)
    dockerfile = generate_dockerfile(profile, repo / "Dockerfile.verirepro", "3.11")
    content = dockerfile.read_text(encoding="utf-8")
    seal = "cp -R /workspace/. /opt/verirepro-repository/"
    assert "/opt/verirepro-repository" in content
    assert content.index("micromamba install") < content.index(seal)
    assert "chmod -R a-w,a+rX /opt/verirepro-repository" in content
