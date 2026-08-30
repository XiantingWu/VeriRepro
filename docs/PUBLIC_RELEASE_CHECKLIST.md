# Public Release Checklist (0.8.2)

Status: **v0.8.1 production release complete; v0.8.2 is a certified candidate awaiting signed-tag, GitHub Release, and PyPI delivery.**

## Runner architecture

- [x] every executable workflow job runs on a GitHub-hosted runner (`ubuntu-latest`); zero jobs use `runs-on: self-hosted`
- [x] zero workflow references private runner labels, runner groups, or private manager infrastructure
- [x] public CI history is retained as quality evidence; no raw self-hosted logs exist by construction
- [x] self-hosted execution authority is none
- [ ] live fork smoke: static contract PASS; live behavioral smoke is deferred until an independent authorized public fork identity is available

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
- [x] stable release tag must equal the current canonical `main` head; ancestry remains defense in depth
- [x] annotated tag, tag/version equality, dereferenced tag/checkout equality, and canonical-main ancestry are required
- [x] wheel and sdist each pass an independent clean-install smoke
- [x] cryptographic tag verification uses `git verify-tag` with a repository-pinned public SSH allowed-signers policy
- [x] no long-lived PyPI token; publish refuses pre-release events
- [x] publish re-runs release/launch/history/source/evidence gates before building
- [x] release signer policy public key is provisioned; no stable tag may be created before the policy is verified
- [x] v1.14.2 PyPI publisher action is pinned to its dereferenced release commit; the annotated tag-object SHA is not used
- [x] exact PyPI publisher runtime-image manifest preflight passes for the v0.8.1 release

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
- [x] release signer policy accepts only `XiantingWu` `ssh-ed25519` authority, including controlled ED25519 rotation

## Governance / security

- [x] main PR rule, strict required checks, and conversation resolution are active in the final ruleset; approvals required remain 0 for the single-maintainer stage
- [x] private vulnerability reporting enabled; SECURITY.md route points to the canonical advisory flow
- [x] issue forms (bug report, feature request, reproduction help) and Dependabot configured
- [x] Dependabot routine updates use explicit minor/patch allow rules without wildcard major ignores; security updates remain eligible
- [x] Dependency Review runs on pull requests with a high-severity threshold and is a required status check
- [x] GitHub Secret Scanning enabled
- [x] GitHub Push Protection enabled
- [x] Dependabot dependency graph, alerts, and security updates enabled
- [x] CodeQL Default Setup enabled and successful on GitHub-hosted analysis
- [x] CODEOWNERS assigns XiantingWu as owner for release-sensitive paths

## Historical v0.8.0 evidence

- [x] previous source/fingerprint/run are labelled historical after release-relevant hardening
- [x] v0.8.0 certification completed on `cd0c962cbf72ebcecea7f5e6af56b98c4d5576ef` in validation run `33316585656`
- [x] v0.8.0 evidence (sanitized) promoted by explicit evidence-only PR as `e262560c4be81b8de1f890ca0effc315b3d6b3f0`
- [x] S1 `ace6683ff24399ff374eec5c05669b67783ffec9`, F1 `4cc5f2d80af9f08a5720cfce273c0f0fe8f2e21af586fffad98f5c939af1b4b8`, old validation, and E1 are labelled historical
- [x] `docs/EVIDENCE.md` distinguishes historical from current evidence and records scientific limits

## Released v0.8.1 authority

- [x] source-hardening main `S3` frozen after the repair PR: `0a0385ab655e4c58a3db527287dc888dacd14f94`
- [x] release-source fingerprint `F3` computed and different from historical F2: `45355990bec900d1efa2faf782eb3099d40927a7a65adf84291c1037a9627613`
- [x] fresh certification (`Validation3`) completed on exact `S3`: run `33324289201`
- [x] fresh evidence (`E3`) sanitized and promoted by an evidence-only PR: `68d50603e8a30b87bcb333cc510a3f85ea6926ce`
- [x] `docs/EVIDENCE.md` updated with S3/F3/Validation3/E3 authority
- [x] v0.8.1 signed annotated tag and GitHub Release published
- [x] v0.8.1 PyPI Trusted Publishing completed successfully (run `33325816551`)
- [x] fresh clean PyPI install verified

## Final quality target

- [x] historical validation recorded 782 tests with 86.4% statement coverage and 79.9% branch coverage
- [x] v0.8.0 historical validation recorded 792 tests with 86.4% statement coverage and 79.9% branch coverage
- [x] 0.8.1 validation recorded 803 tests with 86.4% statement coverage and 79.9% branch coverage
- [x] 0.8.1 build / Twine / independent clean-wheel and clean-sdist install PASS recorded after repair
- [x] native history scan, Gitleaks, and TruffleHog PASS recorded at final audit
- [x] public launch surface, anonymous clone, and quick start PASS re-verified at final audit
- [x] full reachable Git history contains zero private runner / host identity metadata
- [x] TruffleHog verified secrets = 0; unknown/unreviewed candidates = 0; three synthetic fixture candidates reviewed separately

## Immutable v0.8.0 history

- [x] signed annotated tag `v0.8.0` preserved
- [x] GitHub Release `v0.8.0` preserved as published non-prerelease
- [x] PyPI `verirepro==0.8.0` was not published; no upload was attempted after the deterministic publisher-image failure

## Current v0.8.2 certified candidate

- [x] fresh exact-main certification (`Validation4`) on `S4`: run `33333603696`
- [x] release-source fingerprint `F4`: `95904277df77db6e97e83cafe57a351a100c4b3084453c7083edf6cd0baeb324`
- [x] sanitized evidence promoted as `E4`: `028bb7e98b1985f647e46e2e4e349a23ff78bb6b`
- [x] 803 tests with 86.4% statement coverage and 79.9% branch coverage
- [x] discovery 15/15 and bounded planning 3/3
- [x] ReproBench gate: 1 success / 1 partial / 0 failures

## Pending v0.8.2 delivery

- [ ] signed annotated tag `v0.8.2`
- [ ] GitHub Release `v0.8.2`
- [ ] PyPI Trusted Publishing publication for `verirepro==0.8.2`

## Deferred cross-account smoke

- [ ] live fork PR smoke on a second account (static contract PASS; deferred pending an independent authorized public fork identity)
