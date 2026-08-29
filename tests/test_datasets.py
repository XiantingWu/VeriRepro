import json
from pathlib import Path

import pytest

from reproagent.config import DatasetSpec
from reproagent.datasets import (
    DatasetSecurityError,
    _cache_entry,
    _dataset_output_names,
    _download_headers,
    _host_dataset_byte_limit,
    _safe_filename,
    _validate_download_url,
    _validated_sha256,
    download_datasets,
    resolve_dataset_url,
)


def test_dataset_sha256_accepts_normalized_digest():
    digest = "A" * 64
    assert _validated_sha256(digest) == "a" * 64


@pytest.mark.parametrize("value", ["", "abc", "g" * 64, "0" * 63])
def test_dataset_sha256_rejects_malformed_digest(value):
    with pytest.raises(DatasetSecurityError, match="sha256"):
        _validated_sha256(value)


def test_cache_entry_stays_beneath_root(tmp_path: Path):
    root = tmp_path.resolve()
    digest = "1" * 64
    assert _cache_entry(root, digest) == root / digest


@pytest.mark.parametrize(
    "filename",
    ["../escape.bin", "folder/data.bin", "folder\\data.bin", "..", "\x00bad"],
)
def test_dataset_filename_rejects_path_and_control_characters(filename):
    spec = DatasetSpec(
        name="demo",
        url="https://example.com/data.bin",
        filename=filename,
    )
    with pytest.raises(DatasetSecurityError, match="single non-empty file name"):
        _safe_filename(spec)


def test_dataset_filename_uses_remote_basename_safely():
    spec = DatasetSpec(
        name="demo",
        provider="huggingface",
        repo_id="org/data",
        revision="abc123",
        path="nested/train.parquet",
    )
    assert _safe_filename(spec) == "train.parquet"


def test_duplicate_dataset_output_names_are_rejected_case_insensitively():
    specs = (
        DatasetSpec(
            name="one",
            url="https://example.com/one",
            filename="Data.bin",
        ),
        DatasetSpec(
            name="two",
            url="https://example.com/two",
            filename="data.bin",
        ),
    )
    with pytest.raises(DatasetSecurityError, match="duplicate destination filenames"):
        _dataset_output_names(specs)


def test_huggingface_url_is_revision_and_path_scoped():
    spec = DatasetSpec(
        name="demo",
        provider="huggingface",
        repo_id="org/data set",
        revision="refs/pr/1",
        path="nested/file name.parquet",
    )
    url = resolve_dataset_url(spec)
    assert url.startswith("https://huggingface.co/datasets/org/data%20set/resolve/")
    assert "refs%2Fpr%2F1" in url
    assert "nested/file%20name.parquet" in url
    assert url.endswith("?download=true")


def test_huggingface_token_is_not_attached_to_other_providers(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "secret-token")
    hf = DatasetSpec(
        name="hf",
        provider="huggingface",
        repo_id="org/data",
        path="data.bin",
    )
    direct = DatasetSpec(name="direct", url="https://example.com/data.bin")
    assert _download_headers(hf) == {"Authorization": "Bearer secret-token"}
    assert _download_headers(direct) == {}


def test_dataset_url_rejects_localhost_and_embedded_credentials():
    with pytest.raises(DatasetSecurityError, match="not publicly routable"):
        _validate_download_url("https://127.0.0.1/data.bin")
    with pytest.raises(DatasetSecurityError, match="embedded credentials"):
        _validate_download_url("https://user:pass@example.com/data.bin", resolve_dns=False)


def test_dataset_host_budget_env_must_be_positive_integer(monkeypatch):
    monkeypatch.setenv("VERIREPRO_MAX_DATASET_BYTES", "0")
    with pytest.raises(DatasetSecurityError, match="must be positive"):
        _host_dataset_byte_limit()
    monkeypatch.setenv("VERIREPRO_MAX_DATASET_BYTES", "not-an-int")
    with pytest.raises(DatasetSecurityError, match="must be an integer"):
        _host_dataset_byte_limit()


def test_empty_dataset_materialization_writes_secretless_provenance(tmp_path: Path):
    provenance = tmp_path / "dataset-provenance.json"
    downloaded = download_datasets((), tmp_path / "datasets", provenance_path=provenance)
    assert downloaded == []
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert payload == {"datasets": [], "schema_version": 1}
