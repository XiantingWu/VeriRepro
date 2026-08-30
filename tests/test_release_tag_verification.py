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


def test_release_tag_verifier_accepts_multiple_xiantingwu_ed25519_rotation_keys(
    tmp_path: Path,
) -> None:
    root, allowed_signers = _tag_repository(tmp_path, signed=True)
    rotation_key = root / "rotation-signing-key"
    _run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(rotation_key), cwd=root)
    allowed_signers.write_text(
        allowed_signers.read_text(encoding="utf-8")
        + "XiantingWu "
        + rotation_key.with_name(f"{rotation_key.name}.pub").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    assert verify_release_tag(root, tag="v0.8.0", allowed_signers=allowed_signers) == []


def test_release_tag_verifier_rejects_wrong_signer_key(tmp_path: Path) -> None:
    root, allowed_signers = _tag_repository(tmp_path, signed=True)
    wrong_key = root / "wrong-signing-key"
    _run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(wrong_key), cwd=root)
    _run(
        "git",
        "-c",
        "gpg.format=ssh",
        "-c",
        f"user.signingkey={wrong_key}",
        "tag",
        "-s",
        "-m",
        "release",
        "v0.8.1",
        cwd=root,
    )

    errors = verify_release_tag(root, tag="v0.8.1", allowed_signers=allowed_signers)

    assert any("cryptographic" in error for error in errors)


def test_release_tag_verifier_rejects_wrong_principal_only(tmp_path: Path) -> None:
    root, allowed_signers = _tag_repository(tmp_path, signed=True)
    public_key = allowed_signers.read_text(encoding="utf-8").split()[1:]
    allowed_signers.write_text(f"OtherPrincipal {' '.join(public_key)}\n", encoding="utf-8")

    errors = verify_release_tag(root, tag="v0.8.0", allowed_signers=allowed_signers)

    assert any("unauthorized release principal" in error for error in errors)


def test_release_tag_verifier_rejects_expected_and_extra_principal(tmp_path: Path) -> None:
    root, allowed_signers = _tag_repository(tmp_path, signed=True)
    fields = allowed_signers.read_text(encoding="utf-8").split()
    allowed_signers.write_text(
        f"XiantingWu,OtherPrincipal {' '.join(fields[1:])}\n", encoding="utf-8"
    )

    errors = verify_release_tag(root, tag="v0.8.0", allowed_signers=allowed_signers)

    assert any("unauthorized release principal" in error for error in errors)


def test_release_tag_verifier_rejects_rsa_policy_entry(tmp_path: Path) -> None:
    root, allowed_signers = _tag_repository(tmp_path, signed=True)
    rsa_key = root / "rsa-signing-key"
    _run("ssh-keygen", "-q", "-t", "rsa", "-b", "2048", "-N", "", "-f", str(rsa_key), cwd=root)
    rsa_public = rsa_key.with_name(f"{rsa_key.name}.pub").read_text(encoding="utf-8")
    allowed_signers.write_text(f"XiantingWu {rsa_public}", encoding="utf-8")

    errors = verify_release_tag(root, tag="v0.8.0", allowed_signers=allowed_signers)

    assert any("only ssh-ed25519" in error for error in errors)


def test_release_tag_verifier_rejects_malformed_allowed_signers_entry(tmp_path: Path) -> None:
    root, allowed_signers = _tag_repository(tmp_path, signed=True)
    allowed_signers.write_text("XiantingWu ssh-ed25519 not-a-public-key\n", encoding="utf-8")

    errors = verify_release_tag(root, tag="v0.8.0", allowed_signers=allowed_signers)

    assert any("malformed SSH public key" in error for error in errors)
