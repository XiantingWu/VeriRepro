from __future__ import annotations

import errno
import hashlib
import ipaddress
import json
import os
import socket
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - optional cache is bypassed on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]
from urllib.parse import quote, urljoin, urlparse

import requests

from .config import DatasetSpec


class DatasetSecurityError(RuntimeError):
    """Raised when a dataset URL or host destination violates the security policy."""


_REDIRECT_CODES = {301, 302, 303, 307, 308}
_DEFAULT_HOST_DATASET_BYTES = 5 * 1024 * 1024 * 1024
_DEFAULT_HOST_TOTAL_DATASET_BYTES = 10 * 1024 * 1024 * 1024
_DEFAULT_HOST_DATASET_COUNT = 32
_DEFAULT_HOST_DATASET_CACHE_BYTES = 20 * 1024 * 1024 * 1024
_DEFAULT_HOST_DATASET_CACHE_ENTRIES = 4096
_DEFAULT_HOST_DATASET_CACHE_LOCK_TIMEOUT_SECONDS = 300
_CACHE_LOCK_FILENAME = ".verirepro-cache.lock"
_DATASET_PROVENANCE_SCHEMA_VERSION = 1
# Reserve six bytes for the atomic temporary filename prefix/suffix: .<name>.part.
_MAX_DATASET_FILENAME_BYTES = 249


def _positive_env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise DatasetSecurityError(f"{name} must be an integer") from exc
    if value <= 0:
        raise DatasetSecurityError(f"{name} must be positive")
    return value


def _host_dataset_byte_limit() -> int:
    return _positive_env_int("VERIREPRO_MAX_DATASET_BYTES", _DEFAULT_HOST_DATASET_BYTES)


def _host_total_dataset_byte_limit() -> int:
    return _positive_env_int(
        "VERIREPRO_MAX_TOTAL_DATASET_BYTES",
        _DEFAULT_HOST_TOTAL_DATASET_BYTES,
    )


def _host_dataset_count_limit() -> int:
    return _positive_env_int("VERIREPRO_MAX_DATASETS", _DEFAULT_HOST_DATASET_COUNT)


def _host_dataset_cache_byte_limit() -> int:
    return _positive_env_int(
        "VERIREPRO_MAX_DATASET_CACHE_BYTES",
        _DEFAULT_HOST_DATASET_CACHE_BYTES,
    )


def _host_dataset_cache_entry_limit() -> int:
    return _positive_env_int(
        "VERIREPRO_MAX_DATASET_CACHE_ENTRIES",
        _DEFAULT_HOST_DATASET_CACHE_ENTRIES,
    )


def _host_dataset_cache_lock_timeout_seconds() -> int:
    return _positive_env_int(
        "VERIREPRO_DATASET_CACHE_LOCK_TIMEOUT_SECONDS",
        _DEFAULT_HOST_DATASET_CACHE_LOCK_TIMEOUT_SECONDS,
    )


def _validated_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip().lower()
    if len(candidate) != 64 or any(ch not in "0123456789abcdef" for ch in candidate):
        raise DatasetSecurityError("dataset sha256 must be exactly 64 hexadecimal characters")
    return candidate


def _reject_symlink_components(path: Path, *, label: str) -> None:
    if not path.is_absolute():
        raise DatasetSecurityError(f"{label} must be an absolute host path")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                raise DatasetSecurityError(
                    f"{label} must not contain symbolic-link path components"
                )
        except OSError as exc:
            raise DatasetSecurityError(f"could not inspect {label} path components") from exc


def _dataset_cache_root() -> Path | None:
    raw = os.getenv("VERIREPRO_DATASET_CACHE_DIR", "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser()
    _reject_symlink_components(root, label="dataset cache directory")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise DatasetSecurityError("dataset cache directory must be a real directory")
    return root.resolve(strict=True)


class DatasetCacheBusyError(RuntimeError):
    """A safe cache operation could not obtain its bounded advisory lock."""


@contextmanager
def _cache_lock(root: Path):
    if fcntl is None:
        raise DatasetCacheBusyError("host dataset cache locking is unavailable on this platform")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise DatasetCacheBusyError("host dataset cache requires no-follow file-open support")
    lock_path = root / _CACHE_LOCK_FILENAME
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | nofollow, 0o600)
    except OSError as exc:
        raise DatasetSecurityError(
            "dataset cache lock file must be a regular non-symlink file"
        ) from exc

    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise DatasetSecurityError("dataset cache lock file must be a regular file")
        deadline = time.monotonic() + _host_dataset_cache_lock_timeout_seconds()
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DatasetCacheBusyError(
                        "dataset cache lock acquisition timed out"
                    ) from None
                time.sleep(0.05)
            except OSError as exc:
                raise DatasetSecurityError("dataset cache advisory lock failed") from exc
        yield
    finally:
        if locked:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(descriptor)


def _cache_entry(root: Path, digest: str) -> Path:
    digest = _validated_sha256(digest) or ""
    entry = root / digest
    try:
        entry.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise DatasetSecurityError("dataset cache entry escaped the cache root") from exc
    return entry


def _cache_usage(root: Path) -> tuple[int, int]:
    entries = 0
    total = 0
    entry_limit = _host_dataset_cache_entry_limit()
    byte_limit = _host_dataset_cache_byte_limit()
    try:
        with os.scandir(root) as iterator:
            for item in iterator:
                if item.name == _CACHE_LOCK_FILENAME or item.is_symlink():
                    continue
                try:
                    if not item.is_file(follow_symlinks=False):
                        continue
                    size = item.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                entries += 1
                total += max(0, size)
                if entries >= entry_limit or total >= byte_limit:
                    return entries, total
    except OSError as exc:
        raise DatasetSecurityError("could not inspect dataset cache directory") from exc
    return entries, total


def _cache_can_store(root: Path, size: int) -> bool:
    entries, total = _cache_usage(root)
    return (
        entries < _host_dataset_cache_entry_limit()
        and total + size <= _host_dataset_cache_byte_limit()
    )


def _open_cache_entry_no_follow(entry: Path) -> int | None:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise DatasetCacheBusyError("host dataset cache requires no-follow file-open support")
    try:
        descriptor = os.open(entry, os.O_RDONLY | nofollow)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOENT}:
            return None
        raise DatasetSecurityError("could not safely open dataset cache entry") from exc
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        return None
    return descriptor


def _cache_entry_sha256(entry: Path) -> str | None:
    descriptor = _open_cache_entry_no_follow(entry)
    if descriptor is None:
        return None
    digest = hashlib.sha256()
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest().lower()


def _copy_cache_entry(
    entry: Path,
    temporary: Path,
    expected: str,
    effective_limit: int,
) -> tuple[bool, int]:
    descriptor = _open_cache_entry_no_follow(entry)
    if descriptor is None:
        return False, 0
    digest = hashlib.sha256()
    total = 0
    try:
        with temporary.open("xb") as target:
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > effective_limit:
                    raise DatasetSecurityError("cached dataset exceeds effective host byte limit")
                target.write(chunk)
                digest.update(chunk)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    if digest.hexdigest().lower() != expected:
        temporary.unlink(missing_ok=True)
        return False, 0
    return True, total


def _store_cache_entry(root: Path, source: Path, digest: str, size: int) -> str:
    entry = _cache_entry(root, digest)
    if entry.is_symlink():
        return "miss_not_stored_unsafe"
    if entry.exists():
        if _cache_entry_sha256(entry) == digest:
            return "already_present"
        if not entry.is_file():
            return "miss_not_stored_unsafe"
        entry.unlink()
    if not _cache_can_store(root, size):
        return "miss_not_stored_budget"
    temporary = root / f".{digest}.{uuid.uuid4().hex}.part"
    try:
        with source.open("rb") as input_handle, temporary.open("xb") as output_handle:
            copied = 0
            check = hashlib.sha256()
            for chunk in iter(lambda: input_handle.read(1024 * 1024), b""):
                copied += len(chunk)
                output_handle.write(chunk)
                check.update(chunk)
        if copied != size or check.hexdigest().lower() != digest:
            raise DatasetSecurityError("dataset changed while populating the host cache")
        temporary.replace(entry)
    finally:
        temporary.unlink(missing_ok=True)
    return "stored"


def _provenance_source(spec: DatasetSpec) -> dict[str, str]:
    provider = spec.provider.lower()
    if provider == "url":
        parsed = urlparse(spec.url or "")
        origin = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return {"provider": "url", "origin": origin}
    if provider == "huggingface":
        return {
            "provider": "huggingface",
            "repo_id": spec.repo_id or "",
            "revision": spec.revision or "main",
            "path": spec.path or "",
        }
    return {
        "provider": "zenodo",
        "record_id": spec.record_id or "",
        "file": spec.file or "",
    }


def _write_dataset_provenance(path: Path, records: list[dict[str, object]]) -> None:
    if path.is_symlink():
        raise DatasetSecurityError("dataset provenance destination must not be a symbolic link")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    payload = {
        "schema_version": _DATASET_PROVENANCE_SCHEMA_VERSION,
        "datasets": records,
    }
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_filename(value: str, *, label: str) -> str:
    """Validate one host-side filename component without silently fixing traversal."""
    candidate = value.strip()
    if (
        not candidate
        or candidate in {".", ".."}
        or "/" in candidate
        or "\\" in candidate
        or "\x00" in candidate
        or any(ord(character) < 32 for character in candidate)
    ):
        raise DatasetSecurityError(
            f"{label} must be a single non-empty file name without path separators or control characters"
        )
    if len(candidate.encode("utf-8")) > _MAX_DATASET_FILENAME_BYTES:
        raise DatasetSecurityError(
            f"{label} exceeds the {_MAX_DATASET_FILENAME_BYTES}-byte filename limit"
        )
    return candidate


def _remote_basename(value: str) -> str | None:
    normalized = value.replace("\\", "/")
    candidate = normalized.rsplit("/", 1)[-1].strip()
    if not candidate:
        return None
    return _local_filename(candidate, label="dataset remote file name")


def _safe_filename(spec: DatasetSpec) -> str:
    if spec.filename:
        return _local_filename(spec.filename, label="dataset filename")
    if spec.path:
        candidate = _remote_basename(spec.path)
        if candidate:
            return candidate
    if spec.file:
        candidate = _remote_basename(spec.file)
        if candidate:
            return candidate
    if spec.url:
        candidate = _remote_basename(urlparse(spec.url).path)
        if candidate:
            return candidate
    return _local_filename(f"{spec.name}.data", label="dataset fallback filename")


def _host_is_public(host: str) -> bool:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return literal.is_global

    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise DatasetSecurityError(f"could not resolve dataset host: {host}") from exc
    if not addresses:
        raise DatasetSecurityError(f"dataset host resolved to no addresses: {host}")
    found = False
    for entry in addresses:
        raw = entry[4][0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        found = True
        if not address.is_global:
            return False
    if not found:
        raise DatasetSecurityError(f"dataset host resolved to no usable IP addresses: {host}")
    return True


def _validate_download_url(url: str, *, resolve_dns: bool = True) -> None:
    parsed = urlparse(url)
    allow_http = os.getenv("VERIREPRO_ALLOW_INSECURE_HTTP", "").strip() == "1"
    if parsed.scheme not in ({"https", "http"} if allow_http else {"https"}):
        raise DatasetSecurityError("dataset downloads require HTTPS")
    if not parsed.hostname:
        raise DatasetSecurityError("dataset URL has no hostname")
    if parsed.username or parsed.password:
        raise DatasetSecurityError("dataset URLs with embedded credentials are not allowed")
    if resolve_dns and not _host_is_public(parsed.hostname):
        raise DatasetSecurityError(f"dataset host is not publicly routable: {parsed.hostname}")


def _safe_get(url: str, *, stream: bool, timeout: int, headers: dict[str, str] | None = None):
    current = url
    credential_host = urlparse(url).hostname if headers else None
    for _ in range(6):
        _validate_download_url(current)
        current_host = urlparse(current).hostname
        request_headers = headers if credential_host and current_host == credential_host else {}
        response = requests.get(
            current,
            stream=stream,
            timeout=timeout,
            headers=request_headers or {},
            allow_redirects=False,
        )
        if response.status_code not in _REDIRECT_CODES:
            return response
        location = response.headers.get("Location")
        response.close()
        if not location:
            raise DatasetSecurityError("dataset redirect did not include a Location header")
        current = urljoin(current, location)
    raise DatasetSecurityError("dataset download exceeded the redirect limit")


def _huggingface_url(spec: DatasetSpec) -> str:
    assert spec.repo_id and spec.path
    repo_id = quote(spec.repo_id, safe="/")
    revision = quote(spec.revision or "main", safe="")
    remote_path = quote(spec.path, safe="/")
    return (
        f"https://huggingface.co/datasets/{repo_id}/resolve/{revision}/{remote_path}?download=true"
    )


def _zenodo_url(spec: DatasetSpec) -> str:
    assert spec.record_id and spec.file
    metadata_url = f"https://zenodo.org/api/records/{quote(spec.record_id, safe='')}"
    response = _safe_get(metadata_url, stream=False, timeout=60)
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError("Zenodo record metadata request failed") from exc
    finally:
        response.close()
    files = payload.get("files", []) if isinstance(payload, dict) else []
    for item in files:
        key = str(item.get("key") or item.get("filename") or item.get("name") or "")
        if key != spec.file:
            continue
        links = item.get("links") or {}
        candidate = links.get("self") or links.get("content") or links.get("download")
        if candidate:
            return str(candidate)
    raise RuntimeError(f"Zenodo record {spec.record_id} does not expose file {spec.file!r}")


def resolve_dataset_url(spec: DatasetSpec) -> str:
    provider = spec.provider.lower()
    if provider == "url":
        assert spec.url
        url = spec.url
    elif provider == "huggingface":
        url = _huggingface_url(spec)
    elif provider == "zenodo":
        url = _zenodo_url(spec)
    else:
        raise ValueError(f"unsupported dataset provider: {spec.provider}")
    _validate_download_url(url, resolve_dns=False)
    return url


def _download_headers(spec: DatasetSpec) -> dict[str, str]:
    if spec.provider.lower() != "huggingface":
        return {}
    token = os.getenv("HF_TOKEN", "").strip() or os.getenv("HUGGING_FACE_HUB_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _existing_is_valid(path: Path, spec: DatasetSpec) -> bool:
    if path.is_symlink() or not path.is_file() or not spec.sha256:
        return False
    return _sha256(path).lower() == spec.sha256.lower()


def _dataset_output_names(specs: tuple[DatasetSpec, ...]) -> tuple[str, ...]:
    names = tuple(_safe_filename(spec) for spec in specs)
    seen: dict[str, str] = {}
    for name in names:
        key = name.casefold()
        previous = seen.get(key)
        if previous is not None:
            raise DatasetSecurityError(
                "dataset declarations resolve to duplicate destination filenames: "
                f"{previous!r} and {name!r}"
            )
        seen[key] = name
    return names


def download_datasets(
    specs: tuple[DatasetSpec, ...],
    destination: Path,
    *,
    provenance_path: Path | None = None,
) -> list[Path]:
    host_count_limit = _host_dataset_count_limit()
    if len(specs) > host_count_limit:
        raise DatasetSecurityError(
            f"manifest declares {len(specs)} datasets, exceeding host limit {host_count_limit}; "
            "raise VERIREPRO_MAX_DATASETS explicitly if this is intentional"
        )

    output_names = _dataset_output_names(specs)
    host_byte_limit = _host_dataset_byte_limit()
    host_total_limit = _host_total_dataset_byte_limit()
    total_materialized = 0
    if destination.is_symlink():
        raise DatasetSecurityError("dataset destination directory must not be a symbolic link")
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    cache_root = _dataset_cache_root()
    downloaded: list[Path] = []
    records: list[dict[str, object]] = []

    for spec, output_name in zip(specs, output_names, strict=True):
        expected = _validated_sha256(spec.sha256)
        total_remaining = host_total_limit - total_materialized
        if total_remaining <= 0:
            raise DatasetSecurityError(
                f"dataset materialization reached host total limit {host_total_limit}; "
                "raise VERIREPRO_MAX_TOTAL_DATASET_BYTES explicitly if this is intentional"
            )
        effective_limit = min(spec.max_bytes, host_byte_limit, total_remaining)
        output = destination / output_name
        try:
            output.resolve(strict=False).relative_to(destination_root)
        except ValueError as exc:
            raise DatasetSecurityError("dataset destination escaped the dataset root") from exc
        if output.is_symlink():
            raise DatasetSecurityError(
                f"dataset destination must not be a symbolic link: {output.name}"
            )

        materialization = "downloaded"
        cache_status = "disabled" if cache_root is None else "uncacheable_unpinned"
        observed: str | None = None
        size = 0

        if expected and _existing_is_valid(output, spec):
            size = output.stat().st_size
            if size > effective_limit:
                raise DatasetSecurityError(
                    "existing verified dataset exceeds effective host byte limit"
                )
            observed = expected
            materialization = "existing_verified"
            cache_status = "not_checked_existing" if cache_root is not None else "disabled"
        else:
            temporary = output.with_name(f".{output.name}.part")
            try:
                temporary.resolve(strict=False).relative_to(destination_root)
            except ValueError as exc:
                raise DatasetSecurityError(
                    "dataset temporary path escaped the dataset root"
                ) from exc
            if temporary.is_symlink():
                raise DatasetSecurityError(
                    f"dataset temporary path must not be a symbolic link: {temporary.name}"
                )
            temporary.unlink(missing_ok=True)

            cache_hit = False
            if expected and cache_root is not None:
                try:
                    with _cache_lock(cache_root):
                        entry = _cache_entry(cache_root, expected)
                        if entry.exists() or entry.is_symlink():
                            cache_hit, size = _copy_cache_entry(
                                entry, temporary, expected, effective_limit
                            )
                            if cache_hit:
                                temporary.replace(output)
                                observed = expected
                                materialization = "cache_hit"
                                cache_status = "hit"
                            else:
                                cache_status = "invalid_ignored"
                        else:
                            cache_status = "miss"
                except DatasetCacheBusyError:
                    cache_status = "bypassed_lock_timeout"

            if not cache_hit:
                url = resolve_dataset_url(spec)
                digest = hashlib.sha256()
                total = 0
                response = None
                try:
                    response = _safe_get(
                        url,
                        stream=True,
                        timeout=120,
                        headers=_download_headers(spec),
                    )
                    response.raise_for_status()
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        try:
                            declared = int(content_length)
                        except ValueError:
                            declared = 0
                        if declared > effective_limit:
                            raise DatasetSecurityError(
                                f"dataset {spec.name} exceeds effective max_bytes before download "
                                f"({declared} > {effective_limit})"
                            )
                    with temporary.open("xb") as handle:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > effective_limit:
                                raise DatasetSecurityError(
                                    f"dataset {spec.name} exceeded effective max_bytes while downloading "
                                    f"({total} > {effective_limit})"
                                )
                            handle.write(chunk)
                            digest.update(chunk)
                    observed = digest.hexdigest().lower()
                    if expected and observed != expected:
                        raise DatasetSecurityError(f"SHA-256 mismatch for dataset {spec.name}")
                    temporary.replace(output)
                    size = total
                except Exception:
                    temporary.unlink(missing_ok=True)
                    raise
                finally:
                    if response is not None:
                        response.close()

                if expected and cache_root is not None:
                    try:
                        with _cache_lock(cache_root):
                            cache_status = _store_cache_entry(cache_root, output, expected, size)
                    except DatasetCacheBusyError:
                        cache_status = "miss_not_stored_lock_timeout"

        total_materialized += size
        downloaded.append(output)
        records.append(
            {
                "name": spec.name,
                "provider": spec.provider.lower(),
                "source": _provenance_source(spec),
                "filename": output.name,
                "bytes": size,
                "sha256": observed or _sha256(output).lower(),
                "expected_sha256": expected,
                "materialization": materialization,
                "cache": cache_status,
            }
        )

    if provenance_path is not None:
        _write_dataset_provenance(provenance_path, records)
    return downloaded
