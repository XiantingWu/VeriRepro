"""Verify a release tag with the repository-pinned public signer policy."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_TAG_NAME = re.compile(r"^v\d+\.\d+\.\d+$")
_SSH_KEY_TYPES = frozenset(
    {
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "sk-ecdsa-sha2-nistp256@openssh.com",
        "sk-ssh-ed25519@openssh.com",
        "ssh-dss",
        "ssh-ed25519",
        "ssh-rsa",
    }
)


def _allowed_signers_path(root: Path, requested: Path, errors: list[str]) -> Path | None:
    candidate = requested if requested.is_absolute() else root / requested
    if candidate.is_symlink():
        errors.append("release signer policy must not be a symlink")
        return None
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        errors.append("release signer policy must remain inside the repository")
        return None
    if not resolved.is_file():
        errors.append("release signer policy is not provisioned")
        return None
    return resolved


def _check_signer_policy(
    path: Path,
    *,
    expected_principal: str,
    errors: list[str],
) -> bool:
    try:
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"could not read release signer policy: {exc}")
        return False

    if "PRIVATE KEY" in contents:
        errors.append("release signer policy must contain public keys only")

    entries = 0
    expected_entries = 0
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 3 or fields[1] not in _SSH_KEY_TYPES:
            errors.append("release signer policy contains an invalid SSH public-key entry")
            continue
        entries += 1
        if fields[0] == expected_principal:
            expected_entries += 1

    if entries == 0:
        errors.append("release signer policy contains no SSH public signer")
    if expected_entries == 0:
        errors.append(f"release signer policy does not authorize principal {expected_principal!r}")
    return not errors


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def verify_release_tag(
    root: Path = ROOT,
    *,
    tag: str,
    allowed_signers: Path = Path(".github/release-signers"),
    expected_principal: str = "XiantingWu",
) -> list[str]:
    """Return failures for an annotated tag without accepting signature-shaped text.

    The final verification command is the cryptographic ``git verify-tag`` check.
    """

    root = Path(root).resolve()
    errors: list[str] = []
    if not _TAG_NAME.fullmatch(tag):
        errors.append("release tag must be an exact vMAJOR.MINOR.PATCH name")

    policy = _allowed_signers_path(root, Path(allowed_signers), errors)
    if policy is not None:
        _check_signer_policy(policy, expected_principal=expected_principal, errors=errors)

    tag_type = _git(root, "cat-file", "-t", tag)
    if tag_type.returncode != 0 or tag_type.stdout.strip() != "tag":
        errors.append("release tag must point to an annotated tag object")

    if policy is None or errors:
        return errors

    verified = _git(
        root,
        "-c",
        "gpg.format=ssh",
        "-c",
        f"gpg.ssh.allowedSignersFile={policy}",
        "verify-tag",
        "--raw",
        tag,
    )
    if verified.returncode != 0:
        errors.append(
            "release tag cryptographic SSH signature verification failed against the "
            "repository-pinned allowed-signers policy"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify an annotated release tag with the pinned public SSH signer policy."
    )
    parser.add_argument("--tag", required=True)
    parser.add_argument("--allowed-signers", type=Path, default=Path(".github/release-signers"))
    parser.add_argument("--expected-principal", default="XiantingWu")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    errors = verify_release_tag(
        args.root,
        tag=args.tag,
        allowed_signers=args.allowed_signers,
        expected_principal=args.expected_principal,
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"PASS: cryptographic SSH verification for annotated tag {args.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
