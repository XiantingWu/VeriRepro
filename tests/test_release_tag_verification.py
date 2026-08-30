from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.verify_release_tag import verify_release_tag


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _tag_repository(tmp_path: Path, *, signed: bool) -> tuple[Path, Path]:
    root = tmp_path / "tag-repository"
    root.mkdir()
    _run("git", "init", "--quiet", cwd=root)
    _run("git", "config", "user.name", "Test Signer", cwd=root)
    _run("git", "config", "user.email", "test-signer@example.invalid", cwd=root)

    key = root / "test-signing-key"
    _run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key), cwd=root)
    public_key = key.with_name(f"{key.name}.pub").read_text(encoding="utf-8").strip()
    allowed_signers = root / "allowed-signers"
    allowed_signers.write_text(f"XiantingWu {public_key}\n", encoding="utf-8")

    (root / "README").write_text("test\n", encoding="utf-8")
    _run("git", "add", "README", cwd=root)
    _run("git", "commit", "--quiet", "-m", "initial", cwd=root)
    if signed:
        _run(
            "git",
            "-c",
            "gpg.format=ssh",
            "-c",
            f"user.signingkey={key}",
            "tag",
            "-s",
            "-m",
            "release",
            "v0.8.0",
            cwd=root,
        )
    else:
        _run(
            "git",
            "tag",
            "-a",
            "-m",
            "-----BEGIN SSH SIGNATURE-----\nfake\n-----END SSH SIGNATURE-----",
            "v0.8.0",
            cwd=root,
        )
    return root, allowed_signers


def test_release_tag_verifier_accepts_valid_test_signature(tmp_path: Path) -> None:
    root, allowed_signers = _tag_repository(tmp_path, signed=True)

    assert verify_release_tag(root, tag="v0.8.0", allowed_signers=allowed_signers) == []


def test_release_tag_verifier_rejects_unsigned_tag(tmp_path: Path) -> None:
    root, allowed_signers = _tag_repository(tmp_path, signed=False)

    errors = verify_release_tag(root, tag="v0.8.0", allowed_signers=allowed_signers)

    assert any("cryptographic" in error for error in errors)


def test_release_tag_verifier_rejects_signature_block_only_tag(tmp_path: Path) -> None:
    root, allowed_signers = _tag_repository(tmp_path, signed=False)

    errors = verify_release_tag(root, tag="v0.8.0", allowed_signers=allowed_signers)

    assert any("cryptographic" in error for error in errors)


def test_release_tag_verifier_rejects_missing_signer_policy(tmp_path: Path) -> None:
    root, _ = _tag_repository(tmp_path, signed=True)

    errors = verify_release_tag(
        root,
        tag="v0.8.0",
        allowed_signers=Path("missing-signers"),
    )

    assert any("not provisioned" in error for error in errors)
