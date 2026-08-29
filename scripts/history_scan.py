from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_BLOB_BYTES = 10 * 1024 * 1024
DEFAULT_TEXT_SCAN_BYTES = 2 * 1024 * 1024

_SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    (
        "github-token",
        re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b"),
    ),
    ("openai-style-token", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)
_CREDENTIAL_URL_PATTERN = re.compile(r"https://[^/\s:@]+:[^@\s/]+@[^\s\"'()]+")
_HOST_PATH_PATTERNS = (
    re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\"),
)
_KNOWN_SYNTHETIC_CREDENTIAL_FIXTURES = frozenset(
    {
        (
            "tests/test_datasets.py",
            "https://" + "user:pass@" + "example.com/data.bin",
        ),
        (
            "tests/test_datasets_downloads.py",
            "https://" + "user:pass@" + "example.com/data.bin",
        ),
        (
            "tests/test_repository_security.py",
            "https://" + "user:pass@" + "github.com/acme/paper",
        ),
        (
            "tests/test_reprobench_entrypoints.py",
            "https://" + "user:pw@" + "example.com/x",
        ),
        (
            "tests/test_sources_acquisition.py",
            "https://" + "user:pw@" + "example.org/a.pdf",
        ),
    }
)
_KNOWN_SYNTHETIC_HOST_FIXTURES = frozenset(
    {
        ("tests/test_history_scan.py", "/" + "Users/privateuser/"),
    }
)
_SENSITIVE_BASENAMES = frozenset(
    {
        ".env",
        ".npmrc",
        ".pypirc",
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
    }
)


@dataclass(frozen=True, order=True)
class Finding:
    category: str
    path: str
    object_sha: str
    size: int


class HistoryScanError(RuntimeError):
    pass


def _git(root: Path, *args: str, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise HistoryScanError(detail)
    return completed.stdout


def _record_object(
    paths_by_sha: dict[str, set[str]],
    shas: list[str],
    sha: str,
    path: str,
) -> None:
    if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
        raise HistoryScanError(f"unexpected Git object id: {sha!r}")
    if sha not in paths_by_sha:
        paths_by_sha[sha] = set()
        shas.append(sha)
    if path:
        paths_by_sha[sha].add(path)


def _reachable_objects(
    root: Path,
    *,
    refs: tuple[str, ...] | None = None,
    include_tree: str | None = None,
) -> tuple[dict[str, set[str]], dict[str, tuple[str, int]]]:
    if refs:
        listing = _git(root, "rev-list", "--objects", *refs)
    else:
        listing = _git(root, "rev-list", "--objects", "--all")

    paths_by_sha: dict[str, set[str]] = {}
    shas: list[str] = []
    for raw in listing.splitlines():
        if not raw:
            continue
        sha, _, path = raw.partition(" ")
        _record_object(paths_by_sha, shas, sha, path)

    if include_tree:
        tree = _git(root, "ls-tree", "-r", "--full-tree", include_tree)
        for raw in tree.splitlines():
            metadata, separator, path = raw.partition("\t")
            if not separator:
                raise HistoryScanError(f"unexpected ls-tree row: {raw!r}")
            parts = metadata.split()
            if len(parts) != 3:
                raise HistoryScanError(f"unexpected ls-tree metadata: {metadata!r}")
            _, kind, sha = parts
            if kind == "blob":
                _record_object(paths_by_sha, shas, sha, path)

    if not shas:
        return {}, {}

    checked = _git(
        root,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        input_text="\n".join(shas) + "\n",
    )
    meta: dict[str, tuple[str, int]] = {}
    for raw in checked.splitlines():
        parts = raw.split()
        if len(parts) != 3:
            raise HistoryScanError(f"unexpected cat-file metadata: {raw!r}")
        sha, kind, raw_size = parts
        meta[sha] = (kind, int(raw_size))
    return paths_by_sha, meta


def _sensitive_path(path: str) -> bool:
    name = Path(path).name.lower()
    if name == ".env.example":
        return False
    if name in _SENSITIVE_BASENAMES:
        return True
    return name.startswith(".env.")


def scan_history(
    root: Path,
    *,
    max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES,
    text_scan_bytes: int = DEFAULT_TEXT_SCAN_BYTES,
    refs: tuple[str, ...] | None = None,
    include_tree: str | None = None,
) -> list[Finding]:
    root = root.resolve()
    if max_blob_bytes < 1 or text_scan_bytes < 1:
        raise ValueError("history scan byte limits must be positive")
    if refs is not None and not refs:
        raise ValueError("history refs must be non-empty when provided")

    paths_by_sha, meta = _reachable_objects(
        root,
        refs=refs,
        include_tree=include_tree,
    )
    findings: set[Finding] = set()

    for sha, paths in paths_by_sha.items():
        kind_size = meta.get(sha)
        if kind_size is None:
            raise HistoryScanError(f"missing metadata for Git object {sha}")
        kind, size = kind_size
        if kind != "blob":
            continue

        display_paths = sorted(paths) or ["<unpathed-blob>"]
        for path in display_paths:
            if _sensitive_path(path):
                findings.add(Finding("sensitive-filename", path, sha, size))
            if size > max_blob_bytes:
                findings.add(Finding("oversized-history-blob", path, sha, size))

        if size > text_scan_bytes:
            continue

        data = subprocess.run(
            ["git", "cat-file", "blob", sha],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if data.returncode != 0:
            raise HistoryScanError(
                data.stderr.decode("utf-8", errors="replace").strip()
                or f"could not read Git blob {sha}"
            )
        text = data.stdout.decode("utf-8", errors="ignore")
        base_categories = {
            category for category, pattern in _SECRET_PATTERNS if pattern.search(text)
        }
        credential_urls = {match.group(0) for match in _CREDENTIAL_URL_PATTERN.finditer(text)}
        host_paths = {
            match.group(0) for pattern in _HOST_PATH_PATTERNS for match in pattern.finditer(text)
        }
        for path in display_paths:
            categories = set(base_categories)
            if any(
                (path, url) not in _KNOWN_SYNTHETIC_CREDENTIAL_FIXTURES for url in credential_urls
            ):
                categories.add("credential-url")
            if any(
                (path, host_path) not in _KNOWN_SYNTHETIC_HOST_FIXTURES for host_path in host_paths
            ):
                categories.add("host-absolute-path")
            for category in categories:
                findings.add(Finding(category, path, sha, size))

    return sorted(findings)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scan durable Git history and, optionally, one candidate tree for high-confidence "
            "credentials, host-specific absolute paths, sensitive tracked filenames, "
            "and unexpectedly large blobs."
        )
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--ref",
        action="append",
        dest="refs",
        help=(
            "history ref to scan; repeat for multiple refs. "
            "When omitted, every local Git ref is scanned."
        ),
    )
    parser.add_argument(
        "--include-tree",
        help=(
            "also scan the current tree of this Git tree-ish without traversing its intermediate history"
        ),
    )
    parser.add_argument("--max-blob-bytes", type=int, default=DEFAULT_MAX_BLOB_BYTES)
    parser.add_argument("--text-scan-bytes", type=int, default=DEFAULT_TEXT_SCAN_BYTES)
    args = parser.parse_args()
    try:
        refs = tuple(args.refs) if args.refs else None
        findings = scan_history(
            args.root,
            max_blob_bytes=args.max_blob_bytes,
            text_scan_bytes=args.text_scan_bytes,
            refs=refs,
            include_tree=args.include_tree,
        )
    except (OSError, ValueError, HistoryScanError) as exc:
        print(f"FAIL: Git history scan could not complete: {exc}", file=sys.stderr)
        return 2

    if findings:
        for item in findings:
            print(
                "FAIL: history hygiene "
                f"category={item.category} path={item.path} "
                f"object={item.object_sha[:12]} size={item.size}",
                file=sys.stderr,
            )
        return 1

    scope = "all local refs" if refs is None else ", ".join(refs)
    if args.include_tree:
        scope += f" plus tree {args.include_tree}"
    print(f"PASS: Git privacy/secret hygiene passed for {scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
