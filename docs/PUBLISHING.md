# Publishing VeriRepro

This document defines the release process for the canonical `XiantingWu/VeriRepro` repository. Releases must be produced from the standalone repository identity recorded in package metadata and release evidence.

## Release invariants

A release is allowed only when all of the following are true:

1. `pyproject.toml`, `reproagent.__version__`, citation metadata, and the release tag carry the same version.
2. `python scripts/launch_surface_check.py` passes and confirms canonical repository URLs, the private-advisory security route, dependency-update automation, and stable-only PyPI publication.
3. The GitHub-hosted CI workflow passes Ruff, the configured mypy surface, branch-coverage measurement, tests, release/launch checks, distribution build, Twine validation, and clean-wheel installation on the exact candidate SHA.
4. Measured coverage meets the release floor of at least 85% statement coverage and 75% branch coverage.
5. `python scripts/release_check.py --require-release-evidence` passes on the exact release tree. For 0.8, this requires version-matched 15-paper discovery evidence, bounded 3-repository environment-planning evidence, and version-matched ReproBench evidence.
6. `python scripts/release_source_check.py` confirms that release-relevant runtime/package/measurement/promotion/public-launch/release-policy bytes are identical to the source fingerprint recorded by the trusted validation run.
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

External/fork PRs are review-only. The normal trust promotion path is:

1. review the PR diff without executing contributor-controlled code on persistent infrastructure;
2. inspect dependency, workflow, network, filesystem, credential, and execution-authority changes;
3. merge accepted changes through the protected maintainer flow;
4. certify only an exact SHA reachable from canonical `main` on the GitHub-hosted validation workflow;
5. produce fresh exact-source release evidence and promote only the sanitized `benchmarks/` evidence surface.

If adversarial fork execution is ever needed, use genuinely disposable GitHub-hosted isolation rather than maintainer-owned infrastructure.

## Repository controls

Before public launch or stable publication:

1. Keep the canonical repository identity frozen. For 0.8 it is `https://github.com/XiantingWu/VeriRepro`.
2. Protect `main` with a ruleset: block force-push and deletion, require successful CI status checks and conversation resolution.
3. Keep every CI/validation job on GitHub-hosted runners; no workflow may use self-hosted runners, private runner labels, or runner groups.
4. Keep GitHub private vulnerability reporting enabled so the configured Security advisory link remains usable.
5. Keep real-paper/LiteLLM smoke isolated from external pull requests.
6. Create a GitHub Environment named `pypi` and require manual approval for deployments to it.
7. Configure PyPI Trusted Publishing for the exact repository, `publish.yml`, and `pypi` Environment.

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

1. Update version and release metadata.
2. Freeze release-relevant source before producing final evidence. The fingerprint covers runtime/package code, layered release policy, public launch policy, measurement/promotion code, Quality/validation/smoke workflows, and the publish workflow.
3. Run CI on the exact candidate head and require all configured quality/build/install gates to pass.
4. Run the GitHub-hosted `VeriRepro validation` workflow at that same source identity.
5. Promote only the validation run's sanitized discovery/planning/ReproBench evidence; do not hand-author release evidence.
6. Re-run `release_check.py --require-release-evidence` and `release_source_check.py` and verify the source fingerprint matches.
7. Create and push a signed **annotated** tag named exactly `vX.Y.Z` from a commit reachable from canonical `main`; `publish.yml` rejects lightweight/unsigned-looking tag objects and non-main-line tag commits.
8. Create a **non-prerelease** GitHub Release for that tag when publishing to stable PyPI.
9. Approve the protected `pypi` deployment only after the release candidate and distributions have already been reviewed.

The publish workflow refuses a release whose tag does not equal `v` plus the version in `pyproject.toml`, requires full Git history, an annotated tag object containing a PGP/SSH signature block, exact checkout/tag agreement, and reachability from canonical `main`; it then rechecks history/launch/release/source gates before building distributions and will not publish the PyPI job for a GitHub prerelease.

## Evidence promotion

Release evidence is measurement output, not hand-authored marketing data. A trusted exact-head validation run produces:

```text
benchmarks/real-paper-smoke-results-0.8.0.json
benchmarks/environment-planning-results-0.8.0.json
benchmarks/reprobench-results-0.8.0/
  manifest.json
  summary.json
  results/
    <task-id>.json
```

The validation workflow stages only sanitized evidence and hands it to a separate writeback job. Paper PDFs, cloned repositories, Docker contexts, workspaces, prompts/responses, credentials, and raw logs remain transient.

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
