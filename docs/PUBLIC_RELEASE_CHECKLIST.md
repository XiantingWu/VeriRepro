# Public Release Checklist (0.8.0)

Status: **final pre-release hardening in progress.** The stable GitHub Release/PyPI publication remains separately unauthorized.

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
- [ ] stable release tag must equal the current canonical `main` head; ancestry remains defense in depth
- [x] annotated tag, tag/version equality, dereferenced tag/checkout equality, and canonical-main ancestry are required
- [ ] wheel and sdist each pass an independent clean-install smoke
- [x] cryptographic tag verification uses `git verify-tag` with a repository-pinned public SSH allowed-signers policy
- [x] no long-lived PyPI token; publish refuses pre-release events
- [x] publish re-runs release/launch/history/source/evidence gates before building
- [x] release signer policy public key is provisioned; no stable tag may be created before the policy is verified

## Release signer

- [x] dedicated production release signer created
- [x] Git transport key not reused
- [x] public signer fingerprint verified
- [x] production public signer policy provisioned
- [x] valid production scratch signature verified
- [x] unsigned tag rejected
- [x] fake signature rejected
- [x] wrong signer rejected
- [x] missing signer policy rejected
- [x] production private key committed = 0
- [ ] release signer policy accepts only `XiantingWu` `ssh-ed25519` authority, including controlled ED25519 rotation

## Governance / security

- [x] main PR rule, strict required checks, and conversation resolution are active in the final ruleset; approvals required remain 0 for the single-maintainer stage
- [x] private vulnerability reporting enabled; SECURITY.md route points to the canonical advisory flow
- [x] issue forms (bug report, feature request, reproduction help) and Dependabot configured
- [ ] Dependabot routine updates use explicit minor/patch allow rules without wildcard major ignores
- [ ] Dependency Review runs on pull requests with a high-severity threshold and is a required status check
- [ ] GitHub Secret Scanning enabled
- [ ] GitHub Push Protection enabled
- [ ] Dependabot dependency graph, alerts, and security updates enabled
- [ ] CodeQL Default Setup enabled and successful
- [x] CODEOWNERS assigns XiantingWu as owner for release-sensitive paths

## Evidence

- [x] previous source/fingerprint/run are labelled historical after release-relevant hardening
- [ ] fresh certification will be completed once on the final hardening main
- [ ] fresh evidence (sanitized) will be promoted by an explicit evidence-only PR
- [x] `docs/EVIDENCE.md` distinguishes historical from current evidence and records scientific limits

## Final quality target

- [x] historical validation recorded 782 tests with 86.4% statement coverage and 79.9% branch coverage
- [ ] current validation records the final test and coverage gates
- [ ] build / Twine / independent clean-wheel and clean-sdist install PASS recorded after hardening
- [x] native history scan, Gitleaks, and TruffleHog PASS recorded at final audit
- [x] public launch surface, anonymous clone, and quick start PASS re-verified at final audit
- [x] full reachable Git history contains zero private runner / host identity metadata

## Deferred (explicit authorization required)

- [ ] signed annotated tag `v0.8.0`
- [ ] GitHub Release
- [ ] PyPI Trusted Publishing publication
- [ ] live fork PR smoke on a second account (static contract PASS; live smoke not yet executed)
