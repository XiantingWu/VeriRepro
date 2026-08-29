# Public Release Checklist (0.8.0)

Status: **engineering-ready, not yet released.** The stable GitHub Release/PyPI publication is intentionally the final launch step and requires a separate explicit authorization.

## Runner architecture

- [x] every executable workflow job runs on a GitHub-hosted runner (`ubuntu-latest`); zero jobs use `runs-on: self-hosted`
- [x] zero workflow references private runner labels, runner groups, or private manager infrastructure
- [x] public CI history is retained as quality evidence; no raw self-hosted logs exist by construction
- [x] `certification/public-manager-policy.json` is absent; the public repository does not depend on any private certification lane
- [ ] pending: confirm the fork live smoke executes on GitHub-hosted runners (see `test_public_ci_contract` / live smoke)

## CI

- [x] `ci.yml` runs `pull_request` and `push main` on GitHub-hosted runners with `contents: read` and `persist-credentials: false`
- [x] pull-request CI is secret-free; no `secrets.*` in ordinary CI
- [x] all third-party Actions pinned to 40-character commit SHAs
- [x] no `pull_request_target` contributor execution
- [x] CPython 3.11/3.12/3.13 compatibility lane on GitHub-hosted runners
- [x] coverage floors: statement >= 85%, branch >= 75% (measured 86.4% / 79.9% on 3.11)
- [x] ruff, ruff format, mypy, history scan, release/launch policy gates in CI

## Validation

- [x] `validation.yml` is `workflow_dispatch`-only, GitHub-hosted, `contents: read`, no automatic evidence writeback
- [x] validation produces sanitized evidence artifact (discovery / planning / ReproBench / certification environment / source fingerprint)
- [x] evidence promotion is an explicit evidence-only PR reviewed by the maintainer

## Publish

- [x] `publish.yml` is GitHub-hosted, release-only, protected `pypi` Environment, `id-token: write`, PyPI Trusted Publishing/OIDC
- [x] no long-lived PyPI token; publish refuses pre-release events
- [x] publish re-runs release/launch/history/source gates before building

## Governance / security

- [x] `main` protected: block force-push and deletion; require CI status checks and conversation resolution
- [x] private vulnerability reporting enabled; SECURITY.md route points to the canonical advisory flow
- [x] issue forms (bug report, feature request, reproduction help) and dependabot configured
- [x] CODEOWNERS assigns XiantingWu as owner for release-sensitive paths

## Evidence

- [ ] pending: fresh Xianting-native certification (15-paper discovery, 3-repository planning, 2-case ReproBench) on GitHub-hosted validation
- [x] historical/imported evidence is labelled historical only; not cited as current certification
- [x] historical evidence for the older measured source only; current Xianting-native certification replaces it
- [x] `docs/EVIDENCE.md` distinguishes historical from current evidence and records scientific limits

## Final quality target

- [x] 747 tests; statement 86.4%; branch 79.9%
- [x] build / Twine / clean-wheel install PASS
- [x] native history scan PASS; Gitleaks/TruffleHog to be re-run at final audit
- [x] public launch surface PASS (`scripts/launch_surface_check.py`)
- [x] anonymous clone + quick start PASS (re-verified at final audit)
- [x] full reachable Git history contains zero private runner / host identity metadata

## Deferred (explicit authorization required)

- [ ] signed annotated tag `v0.8.0`
- [ ] GitHub Release
- [ ] PyPI Trusted Publishing publication
- [ ] live fork PR smoke on a second account (static contract PASS; live smoke not yet executed)