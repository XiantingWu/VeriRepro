# Release Signing Policy

This policy defines the public trust anchor for stable VeriRepro release tags.
Release signing is distinct from Git transport authentication: the key used to
push to GitHub is not the production release-signing key.

## Stable release tags

Stable releases require annotated Git tags with cryptographic SSH signatures.
The release workflow verifies the tag with `git verify-tag` against the
repository-pinned OpenSSH allowed-signers policy at
`.github/release-signers`. Signature-shaped text in an unsigned tag is not a
signature and is rejected.

The authorized release principal is `XiantingWu`. The current public signer is:

```text
Principal: XiantingWu
Algorithm: ED25519
Public key fingerprint: SHA256:qx8lD44v8Y0IXKzxDHRa379+0W/UXnGwOWhwbMqKixo
```

The policy file contains public SSH key material only. The production private
signing key never enters GitHub, the repository, a workflow, an artifact, or a
release log.

## Policy changes and rotation

Signer changes require a normal pull request through protected `main`, with
the policy and its documented fingerprint reviewed by `XiantingWu`. A signer
rotation alone does not invalidate scientific/source certification: signer
authorization is a publication control, while source certification remains
bound to its recorded certified source, release-source fingerprint, validation
run, and evidence.

A compromised or lost signer requires policy rotation before any future stable
release. The old signer must be removed from the public policy, the replacement
public key must be verified independently, and the change must pass the normal
protected-main review and CI path.

## Release verification boundary

Before a stable release is authorized, the tag must be annotated, signed by an
authorized principal, verified cryptographically against
`.github/release-signers`, match the package version, identify the checked-out
commit, and be reachable from canonical `main`. No stable tag is authorized
while the signer policy is missing or fails verification.
