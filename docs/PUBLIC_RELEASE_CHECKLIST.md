# Public Release Checklist (0.8.0)

Status: **P1 hardening candidate, not yet released.** The stable GitHub Release/PyPI publication requires separate explicit authorization.

## Runner architecture

- [x] every executable workflow job runs on a GitHub-hosted runner (`ubuntu-latest`); zero jobs use `runs-on: self-hosted`
- [x] zero workflow references private runner labels, runner groups, or private manager infrastructure
- [x] public CI history is retained as quality evidence; no raw self-hosted logs exist by construction
- [x] self-hosted execution authority is none
- [ ] live fork smoke: static contract PASS; live behavioral smoke is not yet verified

## CI

- [x] `ci.yml` runs `pull_request` and `push main` on GitHub-hosted runners with `contents: read` and `persist-credentials: false`
- [x] pull-request CI is secret-free; no `secrets.*` in ordinary CI
- [x] all third-party Actions pinned to 40-character commit SHAs
- [x] no `pull_request_target` contributor execution
- [x] CPython 3.11/3.12/3.13 compatibility lanes run on GitHub-hosted runners
- [x] explicit timeouts bound all CI jobs
- [x] workflow-level concurrency cancels stale same-PR/branch CI
- [x] coverage floors: statement >= 85%, branch >= 75%
- [x] ruff, ruff format, mypy, history scan, release/launch policy gates in CI

## Validation and evidence

- [x] `validation.yml` is `workflow_dispatch`-only, GitHub-hosted, `contents: read`, and has no branch mutation
- [x] validation produces a sanitized evidence artifact (discovery / planning / ReproBench / certification environment / source fingerprint)
- [x] evidence lifecycle is exact canonical main -> sanitized artifact -> maintainer verification -> explicit evidence-only PR
- [x] no automatic evidence writeback

## Publish

- [x] `publish.yml` is GitHub-hosted, release-only, protected `pypi` Environment, `id-token: write`, PyPI Trusted Publishing/OIDC
- [x] publish uses release tag checkout rather than mutable `target_commitish`
- [x] annotated tag, tag/version equality, dereferenced tag/checkout equality, and main ancestry are required
- [x] cryptographic tag verification uses `git verify-tag` with a repository-pinned public SSH allowed-signers policy
- [x] no long-lived PyPI token; publish refuses pre-release events
- [x] publish re-runs release/launch/history/source/evidence gates before building
- [ ] release signer policy public key is not yet provisioned; no stable tag may be created before it is provisioned

## Governance / security

- [ ] main PR rule, strict required checks, and conversation resolution are active in the final ruleset
- [x] private vulnerability reporting enabled; SECURITY.md route points to the canonical advisory flow
- [x] issue forms (bug report, feature request, reproduction help) and Dependabot configured
- [x] CODEOWNERS assigns XiantingWu as owner for release-sensitive paths

## Evidence

- [ ] fresh certification on exact merged main is pending after P1 hardening
- [ ] fresh evidence is pending after the exact merged-main certification run
- [x] previous source/fingerprint/run are labelled historical after release-relevant hardening
- [x] `docs/EVIDENCE.md` distinguishes historical from current evidence and records scientific limits

## Final quality target

- [ ] fresh test count and coverage recorded after hardening
- [ ] build / Twine / clean-wheel install PASS recorded after hardening
- [ ] native history scan, Gitleaks, and TruffleHog PASS recorded at final audit
- [ ] public launch surface, anonymous clone, and quick start PASS re-verified at final audit
- [ ] full reachable Git history contains zero private runner / host identity metadata

## Deferred (explicit authorization required)

- [ ] signed annotated tag `v0.8.0`
- [ ] GitHub Release
- [ ] PyPI Trusted Publishing publication
- [ ] live fork PR smoke on a second account (static contract PASS; live smoke not yet executed)
