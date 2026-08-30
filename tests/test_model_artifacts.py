from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import reproagent.experiment as experiment_module
import reproagent.model_artifacts as model_artifacts_module
from reproagent.config import ModelArtifactSpec, load_manifest
from reproagent.experiment import run_in_docker
from reproagent.model_artifacts import materialize_model_artifacts

# This file is part of the canonical exact-head gate after the validated runtime
# patch is promoted; keep it free of branch-only harness assumptions.


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


def test_manifest_parses_checksum_bound_model_artifact(tmp_path: Path) -> None:
    digest = "a" * 64
    manifest = tmp_path / "verirepro.yaml"
    manifest.write_text(
        "version: 1\n"
        "model_artifacts:\n"
        "  - name: checkpoint\n"
        "    url: https://example.com/checkpoint.bin\n"
        "    filename: checkpoint.bin\n"
        f"    sha256: {digest}\n",
        encoding="utf-8",
    )
    loaded = load_manifest(manifest)
    assert len(loaded.model_artifacts) == 1
    artifact = loaded.model_artifacts[0]
    assert artifact.name == "checkpoint"
    assert artifact.filename == "checkpoint.bin"
    assert artifact.sha256 == digest


def test_manifest_without_model_artifacts_defaults_to_empty(tmp_path: Path) -> None:
    manifest = tmp_path / "verirepro.yaml"
    manifest.write_text("version: 1\n", encoding="utf-8")
    assert load_manifest(manifest).model_artifacts == ()


def test_model_artifact_requires_sha256(tmp_path: Path) -> None:
    manifest = tmp_path / "verirepro.yaml"
    manifest.write_text(
        "version: 1\n"
        "model_artifacts:\n"
        "  - name: checkpoint\n"
        "    url: https://example.com/checkpoint.bin\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requires 'sha256'"):
        load_manifest(manifest)


def test_huggingface_model_artifact_requires_explicit_revision(tmp_path: Path) -> None:
    manifest = tmp_path / "verirepro.yaml"
    manifest.write_text(
        "version: 1\n"
        "model_artifacts:\n"
        "  - name: checkpoint\n"
        "    provider: huggingface\n"
        "    repo_id: org/model\n"
        "    path: weights.bin\n"
        "    revision: main\n"
        f"    sha256: {'b' * 64}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="immutable revision"):
        load_manifest(manifest)


def test_huggingface_model_materialization_uses_model_namespace_and_sanitized_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = "c" * 64
    captured = []

    def fake_download(specs, destination, *, provenance_path=None):
        captured.extend(specs)
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / "weights.bin"
        output.write_bytes(b"fixture")
        assert provenance_path is not None
        provenance_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "datasets": [
                        {
                            "name": "checkpoint",
                            "provider": "url",
                            "source": {"provider": "url", "origin": "ignored"},
                            "filename": "weights.bin",
                            "bytes": 7,
                            "sha256": digest,
                            "expected_sha256": digest,
                            "materialization": "downloaded",
                            "cache": "stored",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return [output]

    monkeypatch.setattr(model_artifacts_module, "download_datasets", fake_download)
    spec = ModelArtifactSpec(
        name="checkpoint",
        provider="huggingface",
        repo_id="org/model",
        revision="0123456789abcdef",
        path="weights.bin",
        filename="weights.bin",
        sha256=digest,
    )
    provenance = tmp_path / "model-provenance.json"
    downloaded = materialize_model_artifacts(
        (spec,), tmp_path / "models", provenance_path=provenance
    )

    assert downloaded[0].name == "weights.bin"
    adapted = captured[0]
    assert adapted.provider == "url"
    assert adapted.url == (
        "https://huggingface.co/org/model/resolve/0123456789abcdef/weights.bin?download=true"
    )
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert "datasets" not in payload
    record = payload["model_artifacts"][0]
    assert record["provider"] == "huggingface"
    assert record["source"] == {
        "provider": "huggingface",
        "repo_id": "org/model",
        "revision": "0123456789abcdef",
        "path": "weights.bin",
    }
    assert str(tmp_path) not in provenance.read_text(encoding="utf-8")


def test_model_directory_is_mounted_read_only_and_announced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def fake_popen(command, **kwargs):
        del kwargs
        commands.append(list(command))
        return _Process()

    monkeypatch.setattr(experiment_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(experiment_module.os, "getuid", lambda: 1001)
    monkeypatch.setattr(experiment_module.os, "getgid", lambda: 1002)

    output = tmp_path / "out"
    datasets = tmp_path / "datasets"
    models = tmp_path / "models"
    run_in_docker("image", "true", output, datasets, models, timeout=5)

    command = commands[0]
    assert "VERIREPRO_MODEL_DIR=/models" in command
    assert "REPROAGENT_MODEL_DIR=/models" in command
    assert f"{models.resolve()}:/models:ro" in command
    assert "--network" in command
    assert command[command.index("--network") + 1] == "none"


def test_pipeline_materializes_models_before_docker_execution() -> None:
    root = Path(__file__).resolve().parents[1]
    pipeline = (root / "src" / "reproagent" / "pipeline.py").read_text(encoding="utf-8")
    execution = (root / "src" / "reproagent" / "pipeline_execution.py").read_text(encoding="utf-8")
    materialize = pipeline.index("materialize_model_artifacts(")
    execute_call = pipeline.index("execute_experiment(")
    assert materialize < execute_call
    assert 'tuple(getattr(manifest, "model_artifacts", ()))' in pipeline
    assert "model_dir if model_artifacts else None" in pipeline
    assert "result = run_in_docker(" in execution
