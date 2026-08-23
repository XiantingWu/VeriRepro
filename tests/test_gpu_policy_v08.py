from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

import reproagent.experiment as experiment_module
from reproagent.cli import build_parser
from reproagent.config import load_manifest
from reproagent.experiment import run_in_docker
from reproagent.pipeline import _effective_gpu


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


def test_repository_cannot_self_enable_gpu() -> None:
    assert _effective_gpu(False, False) is False
    assert _effective_gpu(True, False) is False
    assert _effective_gpu(False, True) is False
    assert _effective_gpu(True, True) is True


def test_missing_gpu_fields_default_to_cpu() -> None:
    legacy_manifest = SimpleNamespace()
    legacy_plan = SimpleNamespace()
    request = bool(getattr(legacy_manifest, "gpu", False))
    likely = bool(getattr(legacy_plan, "gpu_likely", False))
    assert request is False
    assert likely is False
    assert _effective_gpu(request, True) is False


def test_manifest_gpu_request_is_strict_boolean(tmp_path: Path) -> None:
    path = tmp_path / "verirepro.yaml"
    path.write_text('version: 1\nexperiment:\n  gpu: "true"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="experiment.gpu must be a boolean"):
        load_manifest(path)


def test_manifest_gpu_request_is_configuration_not_authorization(tmp_path: Path) -> None:
    path = tmp_path / "verirepro.yaml"
    path.write_text('version: 1\nexperiment:\n  gpu: true\n', encoding="utf-8")
    manifest = load_manifest(path)
    assert manifest.gpu is True
    assert _effective_gpu(manifest.gpu, False) is False


def test_runtime_adds_gpu_devices_only_when_explicitly_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_popen(command, **kwargs):
        del kwargs
        commands.append(list(command))
        return _Process()

    monkeypatch.setattr(experiment_module.subprocess, "Popen", fake_popen)
    run_in_docker(
        "verirepro-test",
        "python reproduce.py",
        tmp_path / "outputs",
        tmp_path / "datasets",
        gpu=True,
        timeout=5,
    )
    command = commands[0]
    assert command[command.index("--gpus") + 1] == "all"
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--security-opt") + 1] == "no-new-privileges"
    assert command[command.index("--network") + 1] == "none"


def test_runtime_cpu_default_has_no_gpu_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_popen(command, **kwargs):
        del kwargs
        commands.append(list(command))
        return _Process()

    monkeypatch.setattr(experiment_module.subprocess, "Popen", fake_popen)
    run_in_docker(
        "verirepro-test",
        "python reproduce.py",
        tmp_path / "outputs",
        tmp_path / "datasets",
        timeout=5,
    )
    assert "--gpus" not in commands[0]


def test_cli_requires_explicit_allow_gpu_flag() -> None:
    parser = build_parser()
    without = parser.parse_args(["reproduce", "paper.pdf", "--no-execute"])
    with_gpu = parser.parse_args(["reproduce", "paper.pdf", "--no-execute", "--allow-gpu"])
    assert without.allow_gpu is False
    assert with_gpu.allow_gpu is True
