from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.history_scan import scan_history


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _git_output(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    (root / "README.md").write_text("safe\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "safe")
    return root


def test_history_scan_accepts_safe_history(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert scan_history(root) == []


def test_history_scan_finds_deleted_historical_secret(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    secret = root / ".env"
    secret.write_text("TOKEN=ghp_" + "A" * 36 + "\n", encoding="utf-8")
    _git(root, "add", ".env")
    _git(root, "commit", "-m", "accidental secret")
    secret.unlink()
    _git(root, "add", "-u")
    _git(root, "commit", "-m", "remove secret")

    findings = scan_history(root)
    categories = {item.category for item in findings}
    assert "sensitive-filename" in categories
    assert "github-token" in categories


def test_history_scan_finds_deleted_host_absolute_path(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    path = root / "note.txt"
    path.write_text("workspace=/" + "Users/privateuser/build/repo\n", encoding="utf-8")
    _git(root, "add", "note.txt")
    _git(root, "commit", "-m", "host path")
    path.unlink()
    _git(root, "add", "-u")
    _git(root, "commit", "-m", "remove host path")

    findings = scan_history(root)
    assert any(item.category == "host-absolute-path" for item in findings)


def test_history_scan_allows_only_known_repository_fixture_locations(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    synthetic_credential = "https://" + "user:pass@" + "example.com/data.bin"
    synthetic_host = "/" + "Users/privateuser/"

    datasets = root / "tests/test_datasets.py"
    datasets.parent.mkdir(parents=True)
    datasets.write_text(
        f'URL = "{synthetic_credential}"\n',
        encoding="utf-8",
    )
    scanner_test = root / "tests/test_history_scan.py"
    scanner_test.write_text(
        f'PATH = "{synthetic_host}"\n',
        encoding="utf-8",
    )
    _git(root, "add", "tests")
    _git(root, "commit", "-m", "known synthetic fixtures")

    assert scan_history(root) == []


def test_history_scan_rejects_credential_url_outside_known_fixture(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    path = root / "note.txt"
    credential = "https://" + "alice:realistic-secret-value@" + "example.net/private"
    path.write_text(f"endpoint={credential}\n", encoding="utf-8")
    _git(root, "add", "note.txt")
    _git(root, "commit", "-m", "credential url")

    findings = scan_history(root)
    assert any(item.category == "credential-url" for item in findings)


def test_candidate_mode_scans_durable_history_and_current_tree_only(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    durable_sha = _git_output(root, "rev-parse", "HEAD")

    secret = root / ".env"
    secret.write_text("TOKEN=ghp_" + "B" * 36 + "\n", encoding="utf-8")
    _git(root, "add", ".env")
    _git(root, "commit", "-m", "ephemeral construction secret")
    secret.unlink()
    _git(root, "add", "-u")
    _git(root, "commit", "-m", "clean candidate tree")

    assert scan_history(root, refs=(durable_sha,), include_tree="HEAD") == []


def test_candidate_mode_still_rejects_secret_in_current_tree(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    durable_sha = _git_output(root, "rev-parse", "HEAD")

    secret = root / ".env"
    secret.write_text("TOKEN=ghp_" + "C" * 36 + "\n", encoding="utf-8")
    _git(root, "add", ".env")
    _git(root, "commit", "-m", "candidate secret")

    findings = scan_history(root, refs=(durable_sha,), include_tree="HEAD")
    categories = {item.category for item in findings}
    assert "sensitive-filename" in categories
    assert "github-token" in categories
