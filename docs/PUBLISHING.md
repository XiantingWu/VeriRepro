# Publishing VeriRepro

This document defines the release process for the canonical `XiantingWu/VeriRepro` repository. Releases must be produced from the standalone repository identity recorded in package metadata and release evidence.

## Release invariants

A release is allowed only when all of the following are true:

1. `pyproject.toml`, `reproagent.__version__`, citation metadata, and the release tag carry the same version.
2. `python scripts/launch_surface_check.py` passes and confirms canonical repository URLs, the private-advisory security route, dependency-update automation, and stable-only PyPI publication.
3. The GitHub-hosted CI workflow passes Ruff, the configured mypy surface, branch-coverage measurement, tests, release/launch checks, distribution build, Twine validation, and independent clean-wheel and clean-sdist installation on the exact candidate SHA.
4. Measured coverage meets the release floor of at least 85% statement coverage and 75% branch coverage.
5. `python scripts/release_check.py --require-release-evidence` passes on the exact release tree. For 0.8+, this requires version-matched 15-paper discovery evidence, bounded 3-repository environment-planning evidence, and version-matched ReproBench evidence.
6. `python scripts/release_source_check.py` confirms that release-relevant runtime/package/measurement/promotion/public-launch/release-policy, dependency-update, dependency-review, and workflow bytes are identical to the source fingerprint recorded by the trusted validation run.
7. External/fork pull requests run only on GitHub-hosted ephemeral runners with read-only permissions and no secrets; maintainer-owned or persistent infrastructure never executes contributor-controlled code.
8. The repository has a `pypi` GitHub Environment configured with protection rules and required manual approval.
9. PyPI Trusted Publishing is configured for the exact repository, workflow, and environment.
10. No long-lived PyPI API token is stored as a GitHub secret.

GitHub-hosted CI **is** the release-certification dependency. All CI, validation, and certification jobs run on GitHub-hosted ephemeral runners; this public repository never uses maintainer-owned self-hosted runners, private runner labels, or runner groups.

The release-only `publish.yml` workflow is a separate delivery boundary using PyPI Trusted Publishing/OIDC. It is triggered only by a published GitHub Release, never by pull requests, and it is not used to establish source correctness. Source correctness must already have been certified by CI and `VeriRepro validation` before publication begins.

Historical release evidence remains immutable under its own source identity. An unchanged benchmark corpus digest proves benchmark **inputs** are unchanged; it does not prove that newer runtime or policy bytes produced the same measurements.

## Local or trusted-runner preflight

Run from the repository root:

```bash
python -m pip install -e '.[dev]'
ruff check src tests scripts
ruff format --check src tests scripts
mypy
pytest -q --cov=reproagent --cov=verirepro --cov-branch
python scripts/history_scan.py
verirepro --version
python -m verirepro --version
verirepro-reprobench --help
verirepro-reprobench-summary --help
verirepro doctor --json
python scripts/release_check.py
python scripts/launch_surface_check.py
python scripts/release_check.py --require-release-evidence
python scripts/release_source_check.py
rm -rf dist build
python -m build
python -m twine check dist/*
```

The release candidate is not ready if any command fails. Coverage must be measured from the candidate source; do not fabricate or lower a threshold to make a release pass.

## Contribution trust promotion

External/fork PRs run public GitHub-hosted CI. The PR lane establishes contribution quality only; release certification occurs only after accepted source is merged to canonical `main` and validated by VeriRepro validation.

The normal trust promotion path is:

1. run read-only, secret-free PR CI on GitHub-hosted runners;
2. review code, dependency, workflow, network, filesystem, credential, and execution-authority changes;
3. merge accepted changes through the protected maintainer flow;
4. certify only an exact SHA reachable from canonical `main` on the GitHub-hosted validation workflow;
5. verify the sanitized artifact and promote it through an explicit evidence-only PR.

## Repository controls

Before public launch or stable publication:

1. Keep the canonical repository identity frozen. For 0.8 it is `https://github.com/XiantingWu/VeriRepro`.
2. Protect `main` with a ruleset: block force-push and deletion, require successful CI status checks and conversation resolution.
3. Keep every CI/validation job on GitHub-hosted runners; no workflow may use self-hosted runners, private runner labels, or runner groups.
4. Keep GitHub private vulnerability reporting enabled so the configured Security advisory link remains usable.
5. Keep real-paper/model-assisted smoke isolated from external pull requests.
6. Create a GitHub Environment named `pypi` and require manual approval for deployments to it.
7. Configure PyPI Trusted Publishing for the exact repository, `publish.yml`, and `pypi` Environment.
8. Keep Secret Scanning, Push Protection, the dependency graph, Dependabot security updates, and CodeQL Default Setup enabled through GitHub's security control plane.

## Dependency update and PR review controls

Routine Dependabot version updates are explicitly limited to minor and patch
updates for both Python packages and GitHub Actions. This version-update policy
does not suppress Dependabot security updates; major migrations require
deliberate maintainer review.

Every pull request also runs the read-only `Dependency Review` workflow on a
GitHub-hosted runner. It fails on high-severity dependency findings, uses no
secrets or write permissions, and is a required `main` status check after the
workflow has first been verified on a pull request.

## Publisher action pinning

Third-party GitHub Actions must be pinned to dereferenced commit SHAs. For an
annotated upstream tag, the tag-object SHA is not a valid substitute for the
release commit SHA. The v1.14.2 `pypa/gh-action-pypi-publish` action is pinned
to its dereferenced release commit `dc37677b2e1c63e2034f94d8a5b11f265b73ba33`,
not the annotated tag-object SHA `a892a5a61159132606e93a2fa6f4358831b04d26`.

Because Docker-based publishing actions can resolve a runtime image from
`github.action_ref`, the validation workflow performs a read-only manifest
availability preflight for the exact commit image before a candidate is
certified. This preflight does not request OIDC credentials or upload to
PyPI.

If repository setup requires a release-relevant source change, stop and produce fresh trusted evidence from the changed source before release. Documentation-only changes remain outside the release-source fingerprint.

## PyPI Trusted Publishing

Configure PyPI Trusted Publishing with:

```text
PyPI project: verirepro
GitHub owner: XiantingWu
GitHub repository: VeriRepro
Workflow file: publish.yml
Environment: pypi
```

The committed `.github/workflows/publish.yml` intentionally has no username/password/API-token input. Its privileged publish job receives only `id-token: write`, uses the protected `pypi` Environment, and is skipped for GitHub prereleases.

The publish workflow is intentionally separated from contribution validation. Do not add `pull_request`, `pull_request_target`, build hooks, tests, or arbitrary project execution to the OIDC publishing job.

If the repository name or owner changes, update canonical project URLs, security/contact links, PyPI publisher configuration, launch-surface policy, and this document **before** the next trusted release-evidence run.

## Creating a release

For version `X.Y.Z`:

### Stable release prerequisites

Before creating a stable release, confirm all of the following:

- `.github/release-signers` exists.
- `XiantingWu` is authorized by the public signer policy.
- The public-key fingerprint matches the documented policy.
- The dereferenced tag commit equals the current canonical `origin/main` head.
- The release tag is annotated.
- The release tag has a cryptographic signature.
- `git verify-tag` passes against the repository-pinned signer policy.
- The tag name matches the package version.
- The tag commit matches the checked-out commit.
- The tag is reachable from canonical `main` (retained as defense in depth).

1. Update version and release metadata.
2. Freeze release-relevant source before producing final evidence. The fingerprint covers runtime/package code, layered release policy, public launch policy, measurement/promotion code, Quality/validation/smoke workflows, and the publish workflow.
3. Run CI on the exact candidate head and require all configured quality/build/install gates to pass.
4. Run the GitHub-hosted `VeriRepro validation` workflow at that same source identity.
5. Promote only the validation run's sanitized discovery/planning/ReproBench evidence; do not hand-author release evidence.
6. Re-run `release_check.py --require-release-evidence` and `release_source_check.py` and verify the source fingerprint matches.
7. Create and push a cryptographically signed **annotated** tag named exactly `vX.Y.Z` from a commit reachable from canonical `main`; `publish.yml` verifies it with the repository-pinned public SSH signer policy and rejects unsigned or unauthorized tags.
8. Create a **non-prerelease** GitHub Release for that tag when publishing to stable PyPI.
9. Approve the protected `pypi` deployment only after the release candidate and distributions have already been reviewed.

The publish workflow checks out the release tag, refuses a tag that does not equal `v` plus the version in `pyproject.toml`, requires full Git history, an annotated tag object, cryptographic SSH verification against `.github/release-signers`, exact checkout/tag agreement, equality with the current canonical `origin/main` head, and reachability from canonical `main`; it then rechecks history/launch/release/source gates before building distributions and will not publish the PyPI job for a GitHub prerelease. Keep `main` frozen from signed tag creation until the publish workflow completes. If `main` advances and the equality gate fails, reassess the new final head instead of bypassing or weakening the gate. The signer policy must be provisioned with public key material before a stable release tag is created.

`.github/release-signers` is an OpenSSH allowed-signers policy containing public key lines such as `XiantingWu ssh-ed25519 AAAA...`. It must contain no private key, secret, or transport credential. The exact approved public signer and principal must be reviewed before the first stable tag.

## Evidence promotion

Release evidence is measurement output, not hand-authored marketing data. A trusted exact-head validation run produces:

```text
benchmarks/real-paper-smoke-results-X.Y.Z.json
benchmarks/environment-planning-results-X.Y.Z.json
benchmarks/reprobench-results-X.Y.Z/
  manifest.json
  summary.json
  results/
    <task-id>.json
```

The validation workflow stages and uploads only sanitized evidence. It does not modify a branch. Paper PDFs, cloned repositories, Docker contexts, workspaces, prompts/responses, credentials, and raw logs remain transient.

The ReproBench manifest records the trusted Actions run id, workflow name, exact tested source SHA, and deterministic `source_tree_sha256`. Benchmark suite/task bytes are bound separately by SHA-256. Documentation and promoted evidence files are intentionally excluded from the source fingerprint.

After final evidence is produced, documentation/evidence-promotion commits may be made without invalidating the source fingerprint. Changes to release-relevant runtime/package/measurement/promotion/public-launch/release-policy/workflow bytes **do invalidate the evidence** and require a fresh trusted validation run.

## Post-release verification

After publishing:

```bash
python -m venv /tmp/verirepro-release-check
/tmp/verirepro-release-check/bin/python -m pip install --upgrade pip
/tmp/verirepro-release-check/bin/python -m pip install "verirepro==X.Y.Z"
/tmp/verirepro-release-check/bin/verirepro --version
/tmp/verirepro-release-check/bin/python -m verirepro --version
/tmp/verirepro-release-check/bin/verirepro-reprobench --help
/tmp/verirepro-release-check/bin/verirepro-reprobench-summary --help
```

Also verify that the PyPI page renders the README correctly, canonical project links point to this repository, and both wheel and source distribution are present.

## Rollback policy

PyPI releases are immutable. Do not overwrite a bad release. If a release is unusable, yank it when appropriate, fix the issue, increment the version, and publish a new release. Document the incident in `CHANGELOG.md`.
