# Publishing VeriRepro

This document defines the release process for the canonical `XiantingWu/VeriRepro` repository. Releases must be produced from the standalone public repository identity recorded in package metadata and release evidence.

## Release invariants

A release is allowed only when all of the following are true:

1. `pyproject.toml`, `reproagent.__version__`, citation metadata, and the release tag carry the same version.
2. `python scripts/launch_surface_check.py` passes and confirms canonical repository URLs and the private-advisory security route.
3. The local release preflight (below) passes tests, all public CLI diagnostics, release-tree validation, launch-surface validation, wheel/sdist build, Twine metadata validation, and clean-wheel installation.
4. `python scripts/release_check.py --require-release-evidence` passes on the exact release tree. For 0.8, this requires version-matched 15-paper discovery evidence, version-matched bounded 3-repository environment-planning evidence, and the version-matched ReproBench evidence bundle.
5. `python scripts/release_source_check.py` confirms that release-relevant runtime/package/measurement/promotion/public-launch/release-policy bytes are identical to the source fingerprint recorded by the trusted benchmark producer.
6. If PyPI publishing is restored via GitHub Actions, the repository has the `pypi` GitHub Environment configured with protection rules and required manual approval.
7. PyPI credentials (Trusted Publishing via a restored workflow, or a short-lived PyPI API token for manual upload) are configured for the exact repository identity.
8. No long-lived PyPI API token is committed or stored in repository configuration.

This repository intentionally ships without GitHub Actions workflows, so the final trusted-evidence and source-fingerprint gates are executed manually on a trusted machine as part of the release preflight. Source-changing work is expected to differ from the previous release evidence until fresh trusted benchmark evidence is produced; the final evidence/source-integrity checks therefore remain maintainer release gates.

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
2. Protect `main` with branch protection rules. No GitHub Actions workflows are configured; all validation runs on a trusted machine via the preflight checklist.
3. Keep GitHub private vulnerability reporting enabled so the configured Security advisory link is usable.
4. Real-paper/LiteLLM smoke measurement runs only on a trusted machine controlled by the maintainer and never executes untrusted pull-request code.
5. Create a GitHub Environment named `pypi` and require manual approval for deployments to it.
6. Configure PyPI publishing for the exact repository identity (Trusted Publishing if workflows are restored, or a short-lived PyPI API token for manual upload).

If repository setup requires a release-relevant source change, stop and produce fresh trusted evidence from the changed source before release. Documentation-only changes remain outside the release-source fingerprint.

## PyPI publishing

PyPI uploads are performed manually with a short-lived API token, or via Trusted Publishing if the publish workflow is restored.

Manual upload with a short-lived PyPI API token:

```bash
python -m twine upload dist/*   # TWINE_USERNAME=__token__, TWINE_PASSWORD=<short-lived token>
```

If GitHub Actions is restored later, configure PyPI Trusted Publishing with the exact identity:

```text
PyPI project: verirepro
GitHub owner: XiantingWu
GitHub repository: VeriRepro
Workflow file: publish.yml
Environment: pypi
```

A restored publish workflow must have no username/password/API-token input, must receive only `id-token: write` in the protected `pypi` Environment, and must be skipped for GitHub prereleases.

If the repository name or owner changes, update the canonical project URLs, security/contact links, PyPI publisher configuration, launch-surface policy, and this document **before** the next trusted release-evidence run.

## Creating a release

For version `X.Y.Z`:

1. Update `pyproject.toml`, `src/reproagent/__init__.py`, `CHANGELOG.md`, `CITATION.cff`, canonical public metadata, and other release metadata.
2. Freeze release-relevant source before producing final benchmark evidence. The fingerprint covers package/runtime Python code, `pyproject.toml`, the public launch-surface policy, final release/source checks, front-half measurement/promotion scripts, the ReproBench seed runner, and the runtime/release policy scripts.
3. Run the trusted exact-head producer and retain only its sanitized evidence artifact.
4. Promote the exact version-matched discovery/planning evidence with `scripts/record_release_evidence.py`, and promote the same run's sanitized ReproBench bundle. Do not hand-author release evidence.
5. Re-run the full release preflight, including `scripts/launch_surface_check.py` and `scripts/release_source_check.py`, on the exact release commit.
6. Create and push a signed tag named exactly `vX.Y.Z`.
7. Create a **non-prerelease** GitHub Release for that tag when publishing to stable PyPI.
8. Approve the manual PyPI upload only after reviewing the built distributions with `python -m twine check dist/*`.

The release gates (tag equals `v` plus the version in `pyproject.toml`, launch-surface, final release-evidence, and source-fingerprint checks, plus distribution build/Twine validation) are enforced by the manual preflight above. A GitHub prerelease must not be uploaded to stable PyPI.

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

The ReproBench evidence manifest records the trusted Actions run id, workflow name, exact tested source head SHA, and a deterministic `source_tree_sha256`. The source fingerprint includes the front-half measurement/promotion policy, public launch policy, package metadata, and runtime/release policy, so changing any of those release-relevant bytes after measurement invalidates the evidence. Benchmark suite/task bytes are bound separately by their own SHA-256 values; documentation and promoted evidence files are intentionally excluded from the source fingerprint.

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
