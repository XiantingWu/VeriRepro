import fcntl
import hashlib
import json
import os
import socket
from pathlib import Path

import pytest
import requests

from reproagent import datasets as ds
from reproagent.config import DatasetSpec
from reproagent.datasets import (
    DatasetCacheBusyError,
    DatasetSecurityError,
    _cache_entry,
    _download_headers,
    _host_is_public,
    _local_filename,
    _provenance_source,
    _remote_basename,
    _safe_filename,
    _validate_download_url,
    _write_dataset_provenance,
    download_datasets,
    resolve_dataset_url,
)


def sha256_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class FakeResponse:
    def __init__(self, *, status_code=200, headers=None, chunks=(), payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = tuple(chunks)
        self._payload = payload
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        return iter(self._chunks)

    def json(self):
        if self._payload is None:
            raise ValueError("response carried no JSON payload")
        return self._payload

    def close(self):
        self.closed = True


class Recorder:
    def __init__(self, responses, monkeypatch):
        self.responses = list(responses)
        self.calls = []
        monkeypatch.setattr(ds.requests, "get", self)

    def __call__(self, url, *, stream=False, timeout=None, headers=None, allow_redirects=False):
        self.calls.append({"url": url, "stream": stream, "headers": dict(headers or {})})
        return self.responses.pop(0)


_HOST_IPS = {
    "huggingface.co": "140.82.121.3",
    "example.com": "93.184.216.34",
    "zenodo.org": "188.185.79.172",
}


@pytest.fixture(autouse=True)
def offline_dns(monkeypatch):
    def fake_getaddrinfo(host, service, *args, **kwargs):
        address = _HOST_IPS.get(str(host))
        if address is None:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, service or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


@pytest.fixture(autouse=True)
def clean_policy_env(monkeypatch):
    for name in (
        "VERIREPRO_ALLOW_INSECURE_HTTP",
        "VERIREPRO_MAX_DATASET_BYTES",
        "VERIREPRO_MAX_TOTAL_DATASET_BYTES",
        "VERIREPRO_MAX_DATASETS",
        "VERIREPRO_MAX_DATASET_CACHE_BYTES",
        "VERIREPRO_MAX_DATASET_CACHE_ENTRIES",
        "VERIREPRO_DATASET_CACHE_LOCK_TIMEOUT_SECONDS",
        "VERIREPRO_DATASET_CACHE_DIR",
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def download_with_provenance(specs, tmp_path):
    destination = tmp_path / "datasets"
    provenance = tmp_path / "prov.json"
    downloaded = download_datasets(specs, destination, provenance_path=provenance)
    records = json.loads(provenance.read_text(encoding="utf-8"))["datasets"]
    return downloaded, records


def cached_download(monkeypatch, tmp_path, payload):
    root = tmp_path / "cache"
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_DIR", str(root))
    spec = DatasetSpec(
        name="blob",
        url="https://8.8.8.8/blob.bin",
        sha256=sha256_of(payload),
        max_bytes=4096,
    )
    response = FakeResponse(chunks=[payload])
    recorder = Recorder([response], monkeypatch)
    downloaded, records = download_with_provenance((spec,), tmp_path)
    return root, downloaded[0], records[0], recorder, response


def test_download_url_requires_https():
    with pytest.raises(DatasetSecurityError, match="require HTTPS"):
        _validate_download_url("ftp://example.com/data.bin")
    with pytest.raises(DatasetSecurityError, match="require HTTPS"):
        _validate_download_url("file:///etc/passwd")
    with pytest.raises(DatasetSecurityError, match="require HTTPS"):
        _validate_download_url("http://example.com/data.bin", resolve_dns=False)


def test_plain_http_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("VERIREPRO_ALLOW_INSECURE_HTTP", "1")
    assert _validate_download_url("http://example.com/data.bin", resolve_dns=False) is None


def test_download_url_rejects_credentials_and_empty_hostname():
    with pytest.raises(DatasetSecurityError, match="embedded credentials"):
        _validate_download_url("https://user:pass@example.com/data.bin", resolve_dns=False)
    with pytest.raises(DatasetSecurityError, match="no hostname"):
        _validate_download_url("https:///data.bin", resolve_dns=False)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/data.bin",
        "https://10.0.0.7/data.bin",
        "https://192.168.1.10/data.bin",
        "https://169.254.169.254/latest/meta-data",
        "https://0.0.0.0/data.bin",
        "https://[::1]/data.bin",
    ],
)
def test_download_url_rejects_non_global_ip_literals(url):
    with pytest.raises(DatasetSecurityError, match="not publicly routable"):
        _validate_download_url(url)


def test_download_url_accepts_global_ip_literal_without_dns():
    assert _validate_download_url("https://8.8.8.8/data.bin") is None


def test_host_is_public_evaluates_every_dns_answer(monkeypatch):
    def answer(address):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", lambda host, svc, *a, **k: answer("192.168.0.5"))
    assert _host_is_public("internal.example") is False
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, svc, *a, **k: answer("8.8.8.8"))
    assert _host_is_public("public.example") is True

    mixed = [
        (socket.AF_INET, 0, 0, "", ("8.8.8.8", 0)),
        (socket.AF_INET6, 0, 0, "", ("fd00::1", 0)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, svc, *a, **k: mixed)
    with pytest.raises(DatasetSecurityError, match="not publicly routable: mixed.example"):
        _validate_download_url("https://mixed.example/data.bin")


def test_host_is_public_surfaces_resolution_failures(monkeypatch):
    def raise_gaierror(host, svc, *a, **k):
        raise socket.gaierror(socket.EAI_NONAME, "nope")

    monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)
    with pytest.raises(DatasetSecurityError, match="could not resolve dataset host"):
        _host_is_public("missing.example")

    monkeypatch.setattr(socket, "getaddrinfo", lambda host, svc, *a, **k: [])
    with pytest.raises(DatasetSecurityError, match="resolved to no addresses"):
        _host_is_public("empty.example")

    junk = [(socket.AF_INET, 0, 0, "", ("not-an-address", 0))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, svc, *a, **k: junk)
    with pytest.raises(DatasetSecurityError, match="no usable IP addresses"):
        _host_is_public("junk.example")


def test_resolve_dataset_url_rejects_unknown_provider():
    spec = DatasetSpec(name="weird", provider="gcs", url="https://8.8.8.8/x.bin")
    with pytest.raises(ValueError, match="unsupported dataset provider: gcs"):
        resolve_dataset_url(spec)


def test_huggingface_url_quotes_repo_revision_and_path():
    spec = DatasetSpec(
        name="hf",
        provider="huggingface",
        repo_id="org/repo name",
        revision="v1.0",
        path="sub/dir file.parquet",
    )
    assert resolve_dataset_url(spec) == (
        "https://huggingface.co/datasets/org/repo%20name/resolve/v1.0/"
        "sub/dir%20file.parquet?download=true"
    )
    default = resolve_dataset_url(
        DatasetSpec(name="hf", provider="huggingface", repo_id="org/repo", path="data.bin")
    )
    assert "/resolve/main/data.bin?" in default


def test_download_headers_token_precedence(monkeypatch):
    hf = DatasetSpec(name="hf", provider="huggingface", repo_id="o/r", path="p")
    plain = DatasetSpec(name="plain", url="https://8.8.8.8/p")
    assert _download_headers(plain) == {}
    assert _download_headers(hf) == {}
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "fallback-token")
    assert _download_headers(hf) == {"Authorization": "Bearer fallback-token"}
    monkeypatch.setenv("HF_TOKEN", " primary ")
    assert _download_headers(hf) == {"Authorization": "Bearer primary"}


def test_provenance_source_captures_provider_identity():
    direct = DatasetSpec(name="u", url="https://example.com:8443/a/data.bin?q=1")
    hf = DatasetSpec(
        name="h", provider="huggingface", repo_id="org/repo", revision="rev", path="p/f.bin"
    )
    zenodo = DatasetSpec(name="z", provider="zenodo", record_id="42", file="f.bin")
    assert _provenance_source(direct) == {
        "provider": "url",
        "origin": "https://example.com:8443/a/data.bin",
    }
    assert _provenance_source(hf) == {
        "provider": "huggingface",
        "repo_id": "org/repo",
        "revision": "rev",
        "path": "p/f.bin",
    }
    assert _provenance_source(zenodo) == {
        "provider": "zenodo",
        "record_id": "42",
        "file": "f.bin",
    }


@pytest.mark.parametrize("candidate", ["ok.bin", "a" * 249])
def test_local_filename_allows_boundary_lengths(candidate):
    assert _local_filename(candidate, label="dataset filename") == candidate


@pytest.mark.parametrize("oversized", ["a" * 250, "é" * 125])
def test_local_filename_rejects_oversized_names(oversized):
    with pytest.raises(DatasetSecurityError, match="byte filename limit"):
        _local_filename(oversized, label="dataset filename")


def test_remote_basename_normalizes_separators():
    assert _remote_basename("dir\\nested\\file.tar.gz") == "file.tar.gz"
    assert _remote_basename("/") is None
    assert _remote_basename("") is None


def test_safe_filename_prefers_explicit_then_remotes_then_fallback():
    explicit = DatasetSpec(
        name="a",
        url="https://8.8.8.8/net.bin",
        filename="local.bin",
        path="p/x.bin",
        file="f/y.bin",
    )
    from_path = DatasetSpec(
        name="b", provider="huggingface", path="q/from-path.bin", file="f/from-file.bin"
    )
    from_file = DatasetSpec(
        name="c", provider="zenodo", file="f/from-file.bin", url="https://8.8.8.8/from-url.bin"
    )
    from_url = DatasetSpec(name="d", url="https://8.8.8.8/dir/from-url.bin")
    fallback = DatasetSpec(name="fallback", url="https://8.8.8.8/")
    assert _safe_filename(explicit) == "local.bin"
    assert _safe_filename(from_path) == "from-path.bin"
    assert _safe_filename(from_file) == "from-file.bin"
    assert _safe_filename(from_url) == "from-url.bin"
    assert _safe_filename(fallback) == "fallback.data"


def test_cache_entry_requires_hex_digest_and_stays_in_root(tmp_path):
    root = tmp_path.resolve()
    assert _cache_entry(root, "A" * 64) == root / ("a" * 64)
    with pytest.raises(DatasetSecurityError, match="64 hexadecimal"):
        _cache_entry(root, "../escape")
    with pytest.raises(DatasetSecurityError, match="64 hexadecimal"):
        _cache_entry(root, "z" * 64)


def test_dataset_cache_root_unset_returns_none():
    assert ds._dataset_cache_root() is None


def test_dataset_cache_root_creates_and_resolves_directory(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "cache"
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_DIR", str(target))
    assert ds._dataset_cache_root() == target.resolve()
    assert target.is_dir()


def test_dataset_cache_root_rejects_relative_and_symlinked_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_DIR", "relative/cache")
    with pytest.raises(DatasetSecurityError, match="absolute host path"):
        ds._dataset_cache_root()

    real = tmp_path / "real-cache"
    real.mkdir()
    link = tmp_path / "link-cache"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_DIR", str(link))
    with pytest.raises(DatasetSecurityError, match="symbolic-link"):
        ds._dataset_cache_root()


def test_cache_lock_rejects_symlinked_lock_file(tmp_path):
    target = tmp_path / "elsewhere.bin"
    target.write_bytes(b"x")
    (tmp_path / ".verirepro-cache.lock").symlink_to(target)
    with pytest.raises(DatasetSecurityError, match="regular non-symlink file"):
        with ds._cache_lock(tmp_path):
            pass


def test_cache_lock_rejects_non_regular_lock_file(tmp_path):
    os.mkfifo(tmp_path / ".verirepro-cache.lock")
    with pytest.raises(DatasetSecurityError, match="must be a regular file"):
        with ds._cache_lock(tmp_path):
            pass


def test_cache_lock_reports_busy_when_fcntl_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(ds, "fcntl", None)
    with pytest.raises(DatasetCacheBusyError, match="unavailable on this platform"):
        with ds._cache_lock(tmp_path):
            pass


def assert_no_leftover_files(directory: Path) -> None:
    assert sorted(entry.name for entry in directory.iterdir()) == []


def assert_no_cache_poisoning(cache_root: Path) -> None:
    leftovers = [
        entry.name for entry in cache_root.rglob("*") if entry.name != ".verirepro-cache.lock"
    ]
    assert leftovers == []


def test_successful_download_streams_verifies_and_writes_provenance(monkeypatch, tmp_path):
    payload = b"abcdef"
    spec = DatasetSpec(
        name="blob",
        url="https://8.8.8.8/live/blob.bin",
        sha256=sha256_of(payload),
        max_bytes=1024,
    )
    response = FakeResponse(headers={"Content-Length": "6"}, chunks=[b"", b"abc", b"def"])
    recorder = Recorder([response], monkeypatch)
    result = download_datasets((spec,), tmp_path / "datasets", provenance_path=tmp_path / "p.json")
    assert result == [tmp_path / "datasets" / "blob.bin"]
    assert result[0].read_bytes() == payload
    assert recorder.calls[0] == {
        "url": "https://8.8.8.8/live/blob.bin",
        "stream": True,
        "headers": {},
    }
    assert response.closed
    document = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert document["datasets"] == [
        {
            "name": "blob",
            "provider": "url",
            "source": {"provider": "url", "origin": "https://8.8.8.8/live/blob.bin"},
            "filename": "blob.bin",
            "bytes": 6,
            "sha256": sha256_of(payload),
            "expected_sha256": sha256_of(payload),
            "materialization": "downloaded",
            "cache": "disabled",
        }
    ]


def test_download_populates_cache_entry_with_verifiable_copy(monkeypatch, tmp_path):
    payload = b"cache-me"
    root, output, record, recorder, response = cached_download(monkeypatch, tmp_path, payload)
    assert record["cache"] == "stored"
    assert record["materialization"] == "downloaded"
    assert (root / record["sha256"]).read_bytes() == payload
    assert output.read_bytes() == payload
    assert len(recorder.calls) == 1
    assert response.closed


def test_second_download_is_served_from_cache_without_network(monkeypatch, tmp_path):
    payload = b"twice"
    root, _, _, _, _ = cached_download(monkeypatch, tmp_path, payload)
    spec = DatasetSpec(
        name="blob",
        url="https://8.8.8.8/blob.bin",
        sha256=sha256_of(payload),
        max_bytes=4096,
    )
    recorder = Recorder([], monkeypatch)
    downloaded, records = download_with_provenance((spec,), tmp_path / "second-run")
    assert downloaded[0].read_bytes() == payload
    assert records[0]["materialization"] == "cache_hit"
    assert records[0]["cache"] == "hit"
    assert records[0]["sha256"] == sha256_of(payload)
    assert recorder.calls == []
    assert (root / sha256_of(payload)).is_file()


def test_corrupt_cache_entry_is_replaced_after_revalidation(monkeypatch, tmp_path):
    payload = b"fresh-payload"
    root = tmp_path / "cache"
    root.mkdir(parents=True)
    (root / sha256_of(payload)).write_bytes(b"stale-corrupt")
    _, output, record, recorder, _ = cached_download(monkeypatch, tmp_path, payload)
    assert record["cache"] == "stored"
    assert record["materialization"] == "downloaded"
    assert (root / sha256_of(payload)).read_bytes() == payload
    assert output.read_bytes() == payload
    assert len(recorder.calls) == 1


def test_cache_budget_exhaustion_skips_storage(monkeypatch, tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    (root / "occupant").write_bytes(b"0" * 16)
    monkeypatch.setenv("VERIREPRO_MAX_DATASET_CACHE_ENTRIES", "1")
    _, output, record, _, _ = cached_download(monkeypatch, tmp_path, b"tiny")
    assert record["cache"] == "miss_not_stored_budget"
    assert output.read_bytes() == b"tiny"
    assert not (root / sha256_of(b"tiny")).exists()
    assert (root / "occupant").read_bytes() == b"0" * 16


def test_symlinked_cache_entry_is_never_trusted_nor_followed(monkeypatch, tmp_path):
    payload = b"guarded"
    root = tmp_path / "cache"
    root.mkdir()
    sibling = root / "sibling.bin"
    sibling.write_bytes(b"inside")
    (root / sha256_of(payload)).symlink_to(sibling)
    _, output, record, recorder, _ = cached_download(monkeypatch, tmp_path, payload)
    assert record["cache"] == "miss_not_stored_unsafe"
    assert output.read_bytes() == payload
    assert sibling.read_bytes() == b"inside"
    assert (root / sha256_of(payload)).is_symlink()
    assert len(recorder.calls) == 1


def test_cache_entry_symlink_escape_is_rejected(monkeypatch, tmp_path):
    payload = b"escaper"
    root = tmp_path / "cache"
    root.mkdir()
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_DIR", str(root))
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    (root / sha256_of(payload)).symlink_to(outside)
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/blob.bin", sha256=sha256_of(payload), max_bytes=1024
    )
    recorder = Recorder([], monkeypatch)
    with pytest.raises(DatasetSecurityError, match="dataset cache entry escaped"):
        download_datasets((spec,), tmp_path / "datasets")
    assert recorder.calls == []
    assert outside.read_bytes() == b"outside"


def test_directory_cache_entry_blocks_storage(monkeypatch, tmp_path):
    payload = b"dircase"
    root = tmp_path / "cache"
    root.mkdir()
    (root / sha256_of(payload)).mkdir()
    _, output, record, _, _ = cached_download(monkeypatch, tmp_path, payload)
    assert record["cache"] == "miss_not_stored_unsafe"
    assert output.read_bytes() == payload
    assert (root / sha256_of(payload)).is_dir()


def test_checksum_mismatch_discards_partial_file_and_avoids_cache_poisoning(monkeypatch, tmp_path):
    payload = b"tampered-body"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_DIR", str(cache_root))
    spec = DatasetSpec(name="blob", url="https://8.8.8.8/blob.bin", sha256="b" * 64, max_bytes=1024)
    response = FakeResponse(chunks=[payload])
    Recorder([response], monkeypatch)
    destination = tmp_path / "datasets"
    with pytest.raises(DatasetSecurityError, match="SHA-256 mismatch for dataset blob"):
        download_datasets((spec,), destination)
    assert response.closed
    assert not (destination / "blob.bin").exists()
    assert_no_leftover_files(destination)
    assert_no_cache_poisoning(cache_root)


@pytest.mark.parametrize("failure", [requests.ConnectionError("boom"), requests.Timeout("slow")])
def test_transport_failures_leave_no_partial_state(monkeypatch, tmp_path, failure):
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_DIR", str(cache_root))
    spec = DatasetSpec(name="blob", url="https://8.8.8.8/blob.bin", sha256="c" * 64, max_bytes=1024)

    def explode(url, **kwargs):
        raise failure

    monkeypatch.setattr(ds.requests, "get", explode)
    destination = tmp_path / "datasets"
    with pytest.raises(type(failure)):
        download_datasets((spec,), destination)
    assert_no_leftover_files(destination)
    assert_no_cache_poisoning(cache_root)


def test_http_error_status_aborts_before_writing(monkeypatch, tmp_path):
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/blob.bin", sha256=sha256_of(b"x"), max_bytes=1024
    )
    response = FakeResponse(status_code=403, headers={"Content-Length": "1"}, chunks=[b"x"])
    Recorder([response], monkeypatch)
    with pytest.raises(requests.HTTPError):
        download_datasets((spec,), tmp_path / "datasets")
    assert response.closed
    assert_no_leftover_files(tmp_path / "datasets")


def test_declared_content_length_over_limit_rejected_before_transfer(monkeypatch, tmp_path):
    spec = DatasetSpec(
        name="big", url="https://8.8.8.8/big.bin", sha256=sha256_of(b"0123456789"), max_bytes=8
    )
    response = FakeResponse(headers={"Content-Length": "10"}, chunks=[b"0123456789"])
    Recorder([response], monkeypatch)
    with pytest.raises(DatasetSecurityError, match=r"before download \(10 > 8\)"):
        download_datasets((spec,), tmp_path / "datasets")
    assert response.closed
    assert_no_leftover_files(tmp_path / "datasets")


def test_streamed_payload_over_limit_aborts_midway(monkeypatch, tmp_path):
    spec = DatasetSpec(
        name="big", url="https://8.8.8.8/big.bin", sha256=sha256_of(b"A" * 16), max_bytes=8
    )
    response = FakeResponse(chunks=[b"A" * 8, b"A" * 8])
    Recorder([response], monkeypatch)
    with pytest.raises(DatasetSecurityError, match=r"while downloading \(16 > 8\)"):
        download_datasets((spec,), tmp_path / "datasets")
    assert response.closed
    assert_no_leftover_files(tmp_path / "datasets")


def test_malformed_content_length_is_ignored(monkeypatch, tmp_path):
    payload = b"small"
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/blob.bin", sha256=sha256_of(payload), max_bytes=1024
    )
    Recorder(
        [FakeResponse(headers={"Content-Length": "not-a-number"}, chunks=[payload])], monkeypatch
    )
    downloaded, records = download_with_provenance((spec,), tmp_path)
    assert downloaded[0].read_bytes() == payload
    assert records[0]["bytes"] == len(payload)


def test_redirect_chain_is_followed_with_per_hop_validation(monkeypatch, tmp_path):
    payload = b"final-body"
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/start.bin", sha256=sha256_of(payload), max_bytes=1024
    )
    first = FakeResponse(status_code=302, headers={"Location": "https://8.8.4.4/mid.bin"})
    second = FakeResponse(status_code=301, headers={"Location": "/final.bin"})
    third = FakeResponse(chunks=[payload], headers={"Content-Length": str(len(payload))})
    recorder = Recorder([first, second, third], monkeypatch)
    result = download_datasets((spec,), tmp_path / "datasets")
    assert result[0].read_bytes() == payload
    assert [call["url"] for call in recorder.calls] == [
        "https://8.8.8.8/start.bin",
        "https://8.8.4.4/mid.bin",
        "https://8.8.4.4/final.bin",
    ]
    assert third.closed


def test_redirect_to_private_host_is_rejected(monkeypatch, tmp_path):
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/start.bin", sha256=sha256_of(b"x"), max_bytes=64
    )
    recorder = Recorder(
        [FakeResponse(status_code=302, headers={"Location": "https://127.0.0.1/admin.bin"})],
        monkeypatch,
    )
    with pytest.raises(DatasetSecurityError, match="not publicly routable: 127.0.0.1"):
        download_datasets((spec,), tmp_path / "datasets")
    assert len(recorder.calls) == 1


def test_authorization_header_follows_same_host_redirect_only(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "secret-token")
    spec = DatasetSpec(
        name="weights",
        provider="huggingface",
        repo_id="org/model",
        revision="v2",
        path="ckpt.bin",
        sha256=sha256_of(b"hf-bytes"),
        max_bytes=1024,
    )
    cross = FakeResponse(status_code=307, headers={"Location": "https://8.8.8.8/mirror/ckpt.bin"})
    recorder = Recorder([cross, FakeResponse(chunks=[b"hf-bytes"])], monkeypatch)
    result = download_datasets((spec,), tmp_path / "datasets")
    assert result[0].read_bytes() == b"hf-bytes"
    assert recorder.calls[0]["url"].startswith(
        "https://huggingface.co/datasets/org/model/resolve/v2/ckpt.bin"
    )
    assert recorder.calls[0]["headers"] == {"Authorization": "Bearer secret-token"}
    assert recorder.calls[1]["headers"] == {}

    same = FakeResponse(
        status_code=302, headers={"Location": "https://huggingface.co/retry/ckpt.bin"}
    )
    recorder2 = Recorder([same, FakeResponse(chunks=[b"hf-bytes"])], monkeypatch)
    download_datasets((spec,), tmp_path / "datasets2")
    assert recorder2.calls[1]["headers"] == {"Authorization": "Bearer secret-token"}


def test_redirect_without_location_header_is_rejected(monkeypatch, tmp_path):
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/blob.bin", sha256=sha256_of(b"x"), max_bytes=64
    )
    Recorder([FakeResponse(status_code=303)], monkeypatch)
    with pytest.raises(DatasetSecurityError, match="did not include a Location header"):
        download_datasets((spec,), tmp_path / "datasets")


def test_redirect_loop_exceeds_hop_limit(monkeypatch, tmp_path):
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/blob.bin", sha256=sha256_of(b"x"), max_bytes=64
    )
    looping = [
        FakeResponse(status_code=308, headers={"Location": "https://8.8.8.8/blob.bin"})
        for _ in range(8)
    ]
    recorder = Recorder(looping, monkeypatch)
    with pytest.raises(DatasetSecurityError, match="exceeded the redirect limit"):
        download_datasets((spec,), tmp_path / "datasets")
    assert len(recorder.calls) == 6


def test_verified_existing_file_short_circuits_the_network(monkeypatch, tmp_path):
    payload = b"already-here"
    destination = tmp_path / "datasets"
    destination.mkdir()
    (destination / "blob.bin").write_bytes(payload)
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_DIR", str(tmp_path / "cache"))
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/blob.bin", sha256=sha256_of(payload), max_bytes=1024
    )
    recorder = Recorder([], monkeypatch)
    downloaded, records = download_with_provenance((spec,), tmp_path)
    assert downloaded == [destination / "blob.bin"]
    assert records[0]["materialization"] == "existing_verified"
    assert records[0]["cache"] == "not_checked_existing"
    assert records[0]["sha256"] == sha256_of(payload)
    assert recorder.calls == []


def test_corrupt_existing_file_is_replaced_by_verified_download(monkeypatch, tmp_path):
    payload = b"good-bytes"
    destination = tmp_path / "datasets"
    destination.mkdir()
    (destination / "blob.bin").write_bytes(b"stale-garbage")
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/blob.bin", sha256=sha256_of(payload), max_bytes=1024
    )
    recorder = Recorder([FakeResponse(chunks=[payload])], monkeypatch)
    downloaded, records = download_with_provenance((spec,), tmp_path)
    assert downloaded[0].read_bytes() == payload
    assert records[0]["materialization"] == "downloaded"
    assert len(recorder.calls) == 1


def test_verified_existing_file_over_effective_limit_is_rejected(tmp_path):
    payload = b"B" * 12
    destination = tmp_path / "datasets"
    destination.mkdir()
    (destination / "blob.bin").write_bytes(payload)
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/blob.bin", sha256=sha256_of(payload), max_bytes=8
    )
    with pytest.raises(DatasetSecurityError, match="existing verified dataset exceeds"):
        download_datasets((spec,), destination)
    assert (destination / "blob.bin").read_bytes() == payload


def test_symlinked_dataset_destination_is_rejected(tmp_path):
    destination = tmp_path / "datasets"
    destination.mkdir()
    internal = destination / "internal.bin"
    internal.write_bytes(b"inside")
    (destination / "blob.bin").symlink_to(internal)
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/blob.bin", sha256=sha256_of(b"v"), max_bytes=64
    )
    with pytest.raises(DatasetSecurityError, match="must not be a symbolic link: blob.bin"):
        download_datasets((spec,), destination)
    assert internal.read_bytes() == b"inside"

    outside = tmp_path / "victim.bin"
    outside.write_bytes(b"victim")
    (destination / "escape.bin").symlink_to(outside)
    escaper = DatasetSpec(
        name="escape", url="https://8.8.8.8/escape.bin", sha256=sha256_of(b"v"), max_bytes=64
    )
    with pytest.raises(DatasetSecurityError, match="dataset destination escaped"):
        download_datasets((escaper,), destination)
    assert outside.read_bytes() == b"victim"


def test_duplicate_destinations_are_rejected_before_any_side_effect(tmp_path):
    colliding = (
        DatasetSpec(name="one", url="https://8.8.8.8/one", filename="Report.csv"),
        DatasetSpec(name="two", url="https://8.8.8.8/two", filename="report.CSV"),
    )
    destination = tmp_path / "datasets"
    with pytest.raises(DatasetSecurityError, match="'Report.csv' and 'report.CSV'"):
        download_datasets(colliding, destination)
    assert not destination.exists()

    remotes = (
        DatasetSpec(name="a", provider="huggingface", repo_id="org/one", path="data/train.parquet"),
        DatasetSpec(
            name="b", provider="huggingface", repo_id="org/two", path="other/train.parquet"
        ),
    )
    with pytest.raises(DatasetSecurityError, match="duplicate destination filenames"):
        download_datasets(remotes, tmp_path / "other-dest")
    assert not (tmp_path / "other-dest").exists()


def test_traversing_filename_is_rejected_before_materialization(tmp_path):
    spec = DatasetSpec(name="evil", url="https://8.8.8.8/x.bin", filename="../escape.bin")
    destination = tmp_path / "datasets"
    with pytest.raises(DatasetSecurityError, match="single non-empty file name"):
        download_datasets((spec,), destination)
    assert not destination.exists()
    assert not (tmp_path / "escape.bin").exists()


def test_dataset_count_limit_is_enforced(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIREPRO_MAX_DATASETS", "1")
    specs = (
        DatasetSpec(name="a", url="https://8.8.8.8/a.bin", filename="a.bin"),
        DatasetSpec(name="b", url="https://8.8.8.8/b.bin", filename="b.bin"),
    )
    with pytest.raises(DatasetSecurityError, match="manifest declares 2 datasets"):
        download_datasets(specs, tmp_path / "datasets")


def test_total_byte_budget_spans_multiple_datasets(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIREPRO_MAX_TOTAL_DATASET_BYTES", "4")
    first = DatasetSpec(
        name="first",
        url="https://8.8.8.8/first.bin",
        filename="first.bin",
        sha256=sha256_of(b"wxyz"),
        max_bytes=4,
    )
    second = DatasetSpec(
        name="second",
        url="https://8.8.8.8/second.bin",
        filename="second.bin",
        sha256=sha256_of(b"wxyz"),
        max_bytes=4,
    )
    Recorder([FakeResponse(chunks=[b"wxyz"])], monkeypatch)
    with pytest.raises(DatasetSecurityError, match="reached host total limit 4"):
        download_datasets((first, second), tmp_path / "datasets")
    assert (tmp_path / "datasets" / "first.bin").read_bytes() == b"wxyz"


def test_unpinned_dataset_downloads_without_cache_binding(monkeypatch, tmp_path):
    payload = b"unsigned"
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_DIR", str(tmp_path / "cache"))
    spec = DatasetSpec(name="loose", url="https://8.8.8.8/loose.bin", sha256=None, max_bytes=1024)
    Recorder([FakeResponse(chunks=[payload])], monkeypatch)
    downloaded, records = download_with_provenance((spec,), tmp_path)
    assert downloaded[0].read_bytes() == payload
    assert records[0]["sha256"] == sha256_of(payload)
    assert records[0]["expected_sha256"] is None
    assert records[0]["cache"] == "uncacheable_unpinned"
    assert records[0]["materialization"] == "downloaded"
    assert not (tmp_path / "cache" / sha256_of(payload)).exists()


def test_lock_unavailability_degrades_to_direct_download(monkeypatch, tmp_path):
    monkeypatch.setattr(ds, "fcntl", None)
    payload = b"no-lock"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_DIR", str(cache_root))
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/blob.bin", sha256=sha256_of(payload), max_bytes=1024
    )
    Recorder([FakeResponse(chunks=[payload])], monkeypatch)
    downloaded, records = download_with_provenance((spec,), tmp_path)
    assert downloaded[0].read_bytes() == payload
    assert records[0]["materialization"] == "downloaded"
    assert records[0]["cache"] == "miss_not_stored_lock_timeout"
    assert list(cache_root.iterdir()) == []


def test_contended_cache_lock_times_out_and_bypasses(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_LOCK_TIMEOUT_SECONDS", "1")
    root = tmp_path / "cache"
    root.mkdir()
    monkeypatch.setenv("VERIREPRO_DATASET_CACHE_DIR", str(root))
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    holder = os.open(root / ".verirepro-cache.lock", os.O_CREAT | os.O_RDWR | nofollow, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    payload = b"contended"
    spec = DatasetSpec(
        name="blob", url="https://8.8.8.8/blob.bin", sha256=sha256_of(payload), max_bytes=1024
    )
    Recorder([FakeResponse(chunks=[payload])], monkeypatch)
    try:
        downloaded, records = download_with_provenance((spec,), tmp_path)
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)
    assert downloaded[0].read_bytes() == payload
    assert records[0]["materialization"] == "downloaded"
    assert records[0]["cache"] == "miss_not_stored_lock_timeout"
    assert not (root / sha256_of(payload)).exists()


def test_zenodo_record_metadata_selects_requested_file(monkeypatch, tmp_path):
    spec = DatasetSpec(
        name="zd",
        provider="zenodo",
        record_id="12345",
        file="results.csv",
        sha256=sha256_of(b"csv-bytes"),
        max_bytes=1024,
    )
    metadata = FakeResponse(
        payload={
            "files": [
                {"key": "ignored.zip", "links": {"self": "https://zenodo.org/ignored.zip"}},
                {
                    "filename": "results.csv",
                    "links": {"content": "https://zenodo.org/files/results.csv"},
                },
            ]
        }
    )
    body = FakeResponse(chunks=[b"csv-bytes"], headers={"Content-Length": "9"})
    recorder = Recorder([metadata, body], monkeypatch)
    downloaded, records = download_with_provenance((spec,), tmp_path)
    assert recorder.calls[0]["url"] == "https://zenodo.org/api/records/12345"
    assert recorder.calls[0]["stream"] is False
    assert recorder.calls[1]["url"] == "https://zenodo.org/files/results.csv"
    assert downloaded[0].name == "results.csv"
    assert downloaded[0].read_bytes() == b"csv-bytes"
    assert records[0]["source"] == {
        "provider": "zenodo",
        "record_id": "12345",
        "file": "results.csv",
    }


@pytest.mark.parametrize(
    "files",
    [
        [{"key": "results.csv", "links": {"self": "https://zenodo.org/self/results.csv"}}],
        [{"name": "results.csv", "links": {"download": "https://zenodo.org/dl/results.csv"}}],
    ],
)
def test_zenodo_link_key_fallbacks(files, monkeypatch):
    spec = DatasetSpec(name="zd", provider="zenodo", record_id="77", file="results.csv")
    Recorder([FakeResponse(payload={"files": files})], monkeypatch)
    url = resolve_dataset_url(spec)
    assert url.startswith("https://zenodo.org/")


def test_zenodo_missing_file_and_broken_metadata_raise_runtime_error(monkeypatch):
    missing = DatasetSpec(name="zd", provider="zenodo", record_id="9", file="absent.csv")
    Recorder([FakeResponse(payload={"files": [{"key": "other.csv"}]})], monkeypatch)
    with pytest.raises(RuntimeError, match="does not expose file 'absent.csv'"):
        resolve_dataset_url(missing)

    broken = FakeResponse(status_code=500)
    Recorder([broken], monkeypatch)
    with pytest.raises(RuntimeError, match="metadata request failed"):
        resolve_dataset_url(missing)

    Recorder([FakeResponse(payload=None)], monkeypatch)
    with pytest.raises(RuntimeError, match="metadata request failed"):
        resolve_dataset_url(missing)


def test_provenance_symlink_destination_is_rejected(tmp_path):
    real = tmp_path / "real-prov.json"
    real.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "prov.json"
    link.symlink_to(real)
    with pytest.raises(
        DatasetSecurityError, match="provenance destination must not be a symbolic link"
    ):
        download_datasets((), tmp_path / "datasets", provenance_path=link)


def test_provenance_write_creates_parent_directories_atomically(tmp_path):
    target = tmp_path / "audit" / "nested" / "prov.json"
    _write_dataset_provenance(target, [{"name": "x"}])
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {"schema_version": 1, "datasets": [{"name": "x"}]}
    assert sorted(entry.name for entry in target.parent.iterdir()) == ["prov.json"]
