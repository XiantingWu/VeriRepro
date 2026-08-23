# Publishing VeriRepro

This document defines the release process for the canonical `XiantingWu/VeriRepro` repository. Releases must be produced from the standalone public repository identity recorded in package metadata and release evidence.

## Release invariants

A release is allowed only when all of the following are true:

1. `pyproject.toml`, `reproagent.__version__`, citation metadata, and the release tag carry the same version.
2. `python scripts/launch_surface_check.py` passes and confirms canonical repository URLs, the private-advisory security route, dependency-update automation, and stable-only PyPI publication.
3. The latest public `CI` run passes tests, all public CLI diagnostics, release-tree validation, launch-surface validation, wheel/sdist build, Twine metadata validation, and clean-wheel installation.
4. `python scripts/release_check.py --require-release-evidence` passes on the exact release tree. For 0.8, this requires version-matched 15-paper discovery evidence, version-matched bounded 3-repository environment-planning evidence, and the version-matched ReproBench evidence bundle.
5. `python scripts/release_source_check.py` confirms that release-relevant runtime/package/measurement/promotion/public-launch/release-policy bytes are identical to the source fingerprint recorded by the trusted benchmark producer.
6. The repository has the `pypi` GitHub Environment configured with protection rules and required manual approval.
7. PyPI Trusted Publishing is configured for the exact repository, workflow, and environment.
8. No long-lived PyPI API token is stored as a GitHub secret.

Ordinary public pull-request CI intentionally does **not** run the final trusted-evidence or source-fingerprint gates. Source-changing PRs are expected to differ from the previous release evidence until a maintainer produces fresh trusted benchmark evidence. Requiring `release_source_check.py` on every fork PR would make legitimate runtime changes impossible to validate without access to the trusted benchmark producer. The final evidence/source-integrity checks therefore remain maintainer release gates and are enforced again by `publish.yml`.

Historical release evidence remains immutable under its own version. An unchanged benchmark corpus digest proves that benchmark **inputs** are unchanged; it does not prove that a newer discovery/planning implementation produced the same outputs. Therefore a new release cannot reuse older front-half result files after release-relevant discovery/planning source changes.

## Local or trusted-runner preflight

Run from the repository root:

```bash
python -m pip install -e '.[dev]'
pytest -q
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

The release candidate is not ready if any command fails. The ordinary source-tree check may be used during development before versioned evidence exists; it is not a substitute for the final evidence and source-integrity gates.

## Repository controls

Before publishing a stable release:

1. Keep the canonical repository identity frozen before producing final release evidence. For 0.8 that identity is `https://github.com/XiantingWu/VeriRepro`; `pyproject.toml`, `CITATION.cff`, the issue-template security contact, README, and launch-surface policy must agree with it.
2. Protect `main` and require the public **`CI`** workflow before merge. Public CI must remain on GitHub-hosted ephemeral workers and must not receive repository secrets.
3. Keep GitHub private vulnerability reporting enabled so the configured Security advisory link is usable.
4. If maintainer-controlled real-paper or LiteLLM smoke is enabled, isolate it from public fork PRs. Self-hosted or credentialed integration runners must never execute arbitrary fork pull-request code.
5. Create a GitHub Environment named `pypi` and require manual approval for deployments to it.
6. Configure PyPI Trusted Publishing for the exact repository, `publish.yml`, and `pypi` Environment.

If repository setup requires a release-relevant source change, stop and produce fresh trusted evidence from the changed source before release. Documentation-only changes remain outside the release-source fingerprint.

## PyPI Trusted Publishing

Configure PyPI Trusted Publishing with the exact identity that will request the OIDC token:

```text
PyPI project: verirepro
GitHub owner: XiantingWu
GitHub repository: VeriRepro
Workflow file: publish.yml
Environment: pypi
```

The committed `.github/workflows/publish.yml` intentionally has no username/password/API-token input. Its publish job receives only `id-token: write`, uses the protected `pypi` Environment, and is skipped for GitHub prereleases. A prerelease may exercise the build/test job, but it must not publish a stable PyPI artifact.

If the repository name or owner changes, update the canonical project URLs, security/contact links, PyPI publisher configuration, launch-surface policy, and this document **before** the next trusted release-evidence run.

## Creating a release

For version `X.Y.Z`:

1. Update `pyproject.toml`, `src/reproagent/__init__.py`, `CHANGELOG.md`, `CITATION.cff`, canonical public metadata, and other release metadata.
2. Freeze release-relevant source before producing final benchmark evidence. The fingerprint covers package/runtime Python code, `pyproject.toml`, the public launch-surface policy, final release/source checks, front-half measurement/promotion scripts, the ReproBench seed runner, and the public CI/publish workflows.
3. Run the trusted exact-head producer and retain only its sanitized evidence artifact.
4. Promote the exact version-matched discovery/planning evidence with `scripts/record_release_evidence.py`, and promote the same run's sanitized ReproBench bundle. Do not hand-author release evidence.
5. Re-run the full release preflight, including `scripts/launch_surface_check.py` and `scripts/release_source_check.py`, and confirm the required public `CI` check is green on the release commit.
6. Create and push a signed tag named exactly `vX.Y.Z`.
7. Create a **non-prerelease** GitHub Release for that tag when publishing to stable PyPI.
8. Approve the `pypi` deployment only after reviewing the build job and its attached distributions.

The publish workflow refuses a release whose tag does not equal `v` plus the version in `pyproject.toml`, runs the launch-surface, final release-evidence, and source-fingerprint gates before building distributions, and will not publish the PyPI job for a GitHub prerelease.

## Evidence promotion

Release evidence is measurement output, not hand-authored marketing data.

For 0.8, one trusted exact-head validation run produces three release-evidence components:

```text
benchmarks/real-paper-smoke-results-0.8.0.json
benchmarks/environment-planning-results-0.8.0.json
benchmarks/reprobench-results-0.8.0/
  manifest.json
  summary.json
  results/
    <task-id>.json
```

The first two files are promoted from the trusted run's discovery/planning JSON with:

```bash
python scripts/record_release_evidence.py \
  --discovery <trusted-discovery.json> \
  --planning <trusted-planning.json> \
  --release 0.8.0 \
  --run-id <actions-run-id> \
  --head-sha <exact-tested-head> \
  --artifact-id <actions-artifact-id> \
  --artifact-digest <sha256:...>
```

The promotion script requires the full 15-case pinned corpus for 0.8, requires 3/3 bounded environment plans, re-hashes the committed corpus, normalizes host-specific source paths, and records trusted run/head/artifact provenance.

Do not commit `workspaces/`, paper PDFs, cloned third-party repositories, Docker build contexts, provider prompts/responses, credentials, or host-specific diagnostic paths. The release checker recomputes the relevant SHA-256 values and rejects sensitive result fields before publication.

The ReproBench evidence manifest records the trusted Actions run id, workflow name, exact tested source head SHA, and a deterministic `source_tree_sha256`. The source fingerprint includes the front-half measurement/promotion policy, public launch policy, package metadata, CI/publish workflows, and runtime/release policy, so changing any of those release-relevant bytes after measurement invalidates the evidence. Benchmark suite/task bytes are bound separately by their own SHA-256 values; documentation and promoted evidence files are intentionally excluded from the source fingerprint.

After final evidence is produced, documentation/evidence-promotion commits may be made without invalidating the source fingerprint. Changes to release-relevant runtime/package/measurement/promotion/public-launch/release-policy bytes **do invalidate the evidence** and require a new trusted benchmark producer run before release.

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
