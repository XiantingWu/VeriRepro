# Public release checklist

Maintainer checklist for publishing VeriRepro. Source-code checks are versioned and automated where practical; repository-hosting and registry settings must be verified in their respective control planes.

## Repository tree

- [x] public package/CLI/Python namespace is `verirepro`; legacy `reproagent` aliases are explicit 0.x compatibility paths
- [x] package/runtime/citation version is `0.8.0`
- [x] canonical repository URLs are `https://github.com/XiantingWu/VeriRepro`
- [x] Apache-2.0 license
- [x] README has clone/install/no-execution quick start, Python example, evidence semantics, security summary, and honest limitations
- [x] README does not require strict Docker readiness merely to try the no-execution path
- [x] architecture, trust model, environment, GPU, dataset, model-artifact, output, ReproBench, schema, LiteLLM, getting-started, publishing, roadmap, changelog, security, contribution, conduct, and citation documents are current for 0.8
- [x] local-development state and non-public audit ledgers are excluded from standalone export; required public release documents remain present
- [x] `.gitignore` covers virtualenv/build state plus `.env`, `.env.*`, and `.dev.vars` while allowing a future `.env.example`
- [x] issue forms, pull-request template, Security advisory contact, CODE_OF_CONDUCT, CONTRIBUTING, and SECURITY are present
- [x] Dependabot monitors Python dependencies and pinned GitHub Actions weekly
- [x] public CI is designed for GitHub-hosted ephemeral workers with read-only repository permission, no repository secrets, and non-persistent checkout credentials
- [x] publication workflow uses PyPI Trusted Publishing/OIDC and contains no long-lived PyPI token input
- [x] PyPI publish job is skipped for GitHub prereleases
- [x] `scripts/launch_surface_check.py` fails closed on canonical URL/security/publish/dependency-update regressions
- [x] public-doc regression tests reject stale pre-public/incubator wording in the exported user-facing documentation

## Runtime and evidence safety

- [x] model output is proposal-only; deterministic code controls evidence and execution authority
- [x] repository-authored scientific expectations do not self-authorize PASS/FAIL
- [x] remote paper, dataset, model-artifact, repository, path, and output trust boundaries are documented and regression-tested
- [x] third-party experiment runtime uses explicit non-root identity, read-only root filesystem, bounded writable tmpfs, dropped capabilities, `no-new-privileges`, init, PID/CPU/memory limits, and default-deny runtime network
- [x] network and GPU access each require repository request plus independent operator authorization
- [x] dataset cache is checksum-bound and concurrency-hardened
- [x] model/checkpoint artifacts require SHA-256 and mount read-only at `/models`
- [x] persistent output remains available; bounded ephemeral output is available for less-trusted writers
- [x] lock-aware uv/Poetry/conda-lock/Pipenv environment realization is present
- [x] `doctor --strict` provides machine-readable pre-execution readiness
- [x] residual risks remain explicit: Docker build/daemon is not rootless, Git checkout has no hard transfer/working-tree byte quota, persistent output has no portable hard write quota, PDF parsing remains untrusted host work, and NVIDIA hardware is not yet release-certified

## 0.8 release evidence

- [x] version-matched 15-paper discovery evidence committed
- [x] discovery release gate requires 15/15 source-evaluable, repository-found, correct top-1, and evidence-anchored cases
- [x] version-matched bounded 3-repository environment-planning evidence committed and requires 3/3 plans
- [x] version-matched two-case ReproBench seed evidence committed with immutable external repository refs and explicit interventions
- [x] ReproBench keeps successful process execution distinct from scientific PASS when independent evidence is insufficient
- [x] discovery, planning, and ReproBench evidence share trusted measurement provenance
- [x] evidence is bound to deterministic release-source fingerprint `e25cacde58e3d0dcc56a8e38e23a4f71d1c94b87ee38c29364b7949460c56128`
- [x] `release_check.py --require-release-evidence` and `release_source_check.py` fail closed on stale or mutated release-relevant bytes
- [ ] final release commit has green release-evidence and full canonical validation after all documentation/export polish

## GitHub repository controls

Verify these settings on the public repository before announcing the release:

- [ ] repository owner/name is exactly `XiantingWu/VeriRepro`
- [ ] repository description clearly states the project purpose
- [ ] relevant repository topics are configured for discoverability
- [ ] private vulnerability reporting is enabled so `/security/advisories/new` is usable
- [ ] `main` is protected and requires the public `CI` workflow before merge
- [ ] public fork pull requests cannot execute on self-hosted or credentialed maintainer runners
- [ ] maintainer-only real-paper/LiteLLM integrations, if enabled, remain manual and isolated from untrusted fork code
- [ ] repository About/default-branch links are correct
- [ ] public README and documentation have no broken internal links or missing exported files

Suggested description:

```text
Evidence-grounded agent for verifiable computational paper reproduction.
```

Suggested topics:

```text
reproducibility research-software scientific-computing ai-agent paper-reproduction arxiv docker python
```

A clean social-preview image is recommended for discoverability but is not a release-safety requirement.

## PyPI and release controls

- [ ] confirm `verirepro` package-name availability/ownership directly in PyPI at registration time
- [ ] create GitHub Environment `pypi` with required manual approval
- [ ] register PyPI Trusted Publisher for owner `XiantingWu`, repository `VeriRepro`, workflow `publish.yml`, environment `pypi`
- [ ] create signed `v0.8.0` tag from the exact release commit
- [ ] create a non-prerelease GitHub Release only when stable PyPI publication is intended
- [ ] review built wheel/sdist before approving the `pypi` deployment
- [ ] after publish, install `verirepro==0.8.0` in a fresh environment and verify CLI/module entrypoints plus `pip check`
- [ ] verify PyPI renders README and canonical project links correctly

## First-public-day smoke

- [ ] clone the public repository as an unauthenticated user and follow README Quick Start exactly
- [ ] confirm issue forms render and expected labels exist
- [ ] confirm the Security contact opens a private advisory rather than a public issue
- [ ] confirm required CI is green on `main`
- [ ] confirm no `.env`, credentials, private PDFs/datasets, host paths, internal audit ledgers, runner workspaces, or monorepo-only files are present
- [ ] confirm GitHub About metadata and topics make the project discoverable

## Evidence claims

- [x] no claim that arbitrary papers are zero-config reproducible
- [x] no claim that pixel similarity proves semantic scientific agreement
- [x] no use of unverified model claims for scientific PASS/FAIL
- [x] fixed real-paper discovery corpus documents exactly what it measures and what it does not measure
- [x] ReproBench seed records repository/ref/command overrides as interventions rather than autonomous success
- [x] successful program execution remains distinct from scientific PASS when independent evidence is absent

## Optional launch polish

- [ ] short demo GIF/video from a validated no-execution or bounded execution run
- [ ] social preview using the VeriRepro name and the “Models may propose. Deterministic code must verify.” positioning
- [ ] release announcement only after public clone/install/CI checks are green
- [ ] container image publication only if a stable runtime-image distribution becomes necessary
