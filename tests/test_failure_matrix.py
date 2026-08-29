from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from pypdf.errors import PdfReadError

from reproagent.config import DatasetSpec
from reproagent.datasets import (
    DatasetSecurityError,
    _validated_sha256,
    download_datasets,
)
from reproagent.environment import docker_available
from reproagent.llm import LLMConfig, LLMUnavailableError, OpenAICompatibleClient
from reproagent.repository import clone_repository
from reproagent.sources import _download, resolve_paper


class _DatasetResponse:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.headers: dict[str, str] = {}
        self._chunks = chunks
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


def test_paper_download_timeout_is_observable_and_leaves_no_partial_file(tmp_path, monkeypatch):
    destination = tmp_path / "paper.pdf"

    def fail(*args, **kwargs):
        raise requests.Timeout("network timeout")

    monkeypatch.setattr("reproagent.sources._safe_pdf_response", fail)
    with pytest.raises(requests.Timeout):
        _download("https://example.com/paper.pdf", destination, timeout=1)
    assert not destination.exists()
    assert not (tmp_path / ".paper.pdf.part").exists()


def test_malformed_pdf_fails_resolution_with_pdf_error(tmp_path: Path):
    malformed = tmp_path / "broken.pdf"
    malformed.write_bytes(b"not a pdf")
    with pytest.raises(PdfReadError):
        resolve_paper(str(malformed), tmp_path / "run")


def test_git_clone_failure_surfaces_stderr(tmp_path, monkeypatch):
    failed = SimpleNamespace(returncode=128, stderr="repository not found", stdout="")
    monkeypatch.setattr("reproagent.repository.subprocess.run", lambda *args, **kwargs: failed)
    with pytest.raises(RuntimeError, match="repository not found"):
        clone_repository("https://github.com/example/missing", tmp_path / "repo")


def test_missing_repository_revision_is_explicit(tmp_path, monkeypatch):
    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        return SimpleNamespace(returncode=128, stderr="couldn't find remote ref missing", stdout="")

    monkeypatch.setattr("reproagent.repository.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="git fetch 'missing' failed"):
        clone_repository(
            "https://github.com/example/project",
            tmp_path / "repo",
            ref="missing",
        )


def test_dataset_hash_mismatch_input_is_rejected():
    with pytest.raises(DatasetSecurityError):
        _validated_sha256("not-a-sha256")


def test_dataset_checksum_mismatch_removes_partial_materialization(tmp_path, monkeypatch):
    monkeypatch.delenv("VERIREPRO_DATASET_CACHE_DIR", raising=False)
    response = _DatasetResponse((b"payload",))
    monkeypatch.setattr(
        "reproagent.datasets._safe_get",
        lambda *args, **kwargs: response,
    )
    spec = DatasetSpec(
        name="demo",
        url="https://example.com/data.bin",
        filename="data.bin",
        sha256="0" * 64,
        max_bytes=1024,
    )
    destination = tmp_path / "datasets"
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        download_datasets((spec,), destination)
    assert response.closed is True
    assert not (destination / "data.bin").exists()
    assert not (destination / ".data.bin.part").exists()


def test_dataset_network_timeout_removes_partial_materialization(tmp_path, monkeypatch):
    monkeypatch.delenv("VERIREPRO_DATASET_CACHE_DIR", raising=False)

    def fail(*args, **kwargs):
        raise requests.Timeout("dataset unavailable")

    monkeypatch.setattr("reproagent.datasets._safe_get", fail)
    spec = DatasetSpec(
        name="demo",
        url="https://example.com/data.bin",
        filename="data.bin",
        max_bytes=1024,
    )
    destination = tmp_path / "datasets"
    with pytest.raises(requests.Timeout, match="dataset unavailable"):
        download_datasets((spec,), destination)
    assert not (destination / "data.bin").exists()
    assert not (destination / ".data.bin.part").exists()


def test_docker_unavailable_path(monkeypatch):
    monkeypatch.setattr("reproagent.environment.shutil.which", lambda _: None)
    assert docker_available() is False


def test_llm_malformed_json_has_stable_error():
    config = LLMConfig(base_url="https://example.com", api_key="secret", model="demo")
    client = OpenAICompatibleClient(config)
    with pytest.raises(LLMUnavailableError, match="did not return a JSON object"):
        client._parse_json_object("definitely not json")
