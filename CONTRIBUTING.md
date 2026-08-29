# Contributing

Contributions should improve **measurable scientific reproducibility**, not just increase agent complexity.

## Setup

Supported development and package-test interpreters are CPython 3.11–3.13. Maintainer Quality performs the full certification lane on CPython 3.11 and runs the complete pytest suite again on managed CPython 3.12 and 3.13.

```bash
python -m pip install -e '.[dev]'
ruff check src tests scripts
ruff format --check src tests scripts
mypy
pytest -q --cov=reproagent --cov=verirepro --cov-branch --cov-report=term-missing --cov-report=json:coverage.json
python scripts/coverage_gate.py coverage.json --min-statement 85 --min-branch 75
verirepro --version
verirepro doctor --json
python scripts/history_scan.py
python scripts/release_check.py
python scripts/launch_surface_check.py
```

Coverage is measured with branch coverage enabled and the trusted release workflows fail closed below **85% statement coverage** or **75% branch coverage**. Do not lower a quality threshold to make a change pass.

Before proposing a release-facing change, also verify the distribution locally when possible:

```bash
python -m build
python -m twine check dist/*
```

## Design rules

1. Paper text, LLM output, repository code, host-side downloads, and experiment outputs are separate trust domains.
2. LLM output is a proposal, never an authority grant. Model-generated execution plans must pass deterministic validation.
3. Concrete paper claims should carry page/quote evidence whenever possible.
4. Missing information should remain missing; do not hide uncertainty behind undocumented defaults.
5. Every environment decision should be traceable to repository evidence or an explicit VeriRepro fallback.
6. Tests must not require a paid LLM call, GPU, or external network unless the test is explicitly marked as an integration smoke.
7. Runtime code must remain standalone and must not import unpublished sibling-project or monorepo-only modules.
8. Host-side URL fetchers must consider SSRF, redirects, byte limits, partial writes, integrity checks, and credential forwarding.
9. Do not add a scientific PASS/FAIL signal unless its semantics and tolerance are machine-testable.
10. External/fork pull requests run only on GitHub-hosted ephemeral runners with read-only permissions and no secrets; maintainer-owned or persistent infrastructure must never execute contributor-controlled code. Only an exact SHA reachable from canonical `main` may be certified by the public GitHub-hosted validation workflow.
11. The preferred public namespace is `verirepro`; `reproagent` is a compatibility/implementation namespace during 0.x. Public symbols must remain contract-tested across both surfaces.
12. Pipeline policy, third-party execution, scientific verification, reporting, and release policy must remain independently testable instead of accumulating in god modules.

## Pull requests

A useful PR explains:

- the reproducibility failure mode it addresses;
- the deterministic evidence contract;
- tests or a public minimal fixture;
- any new network/filesystem/credential/execution authority;
- backwards-compatibility impact on the manifest or report schema.

Run the full local suite before opening a PR:

```bash
ruff check src tests scripts
ruff format --check src tests scripts
mypy
pytest -q --cov=reproagent --cov=verirepro --cov-branch --cov-report=term-missing --cov-report=json:coverage.json
python scripts/coverage_gate.py coverage.json --min-statement 85 --min-branch 75
verirepro doctor --json
python scripts/history_scan.py
python scripts/release_check.py
python scripts/launch_surface_check.py
```

### External and fork pull requests

VeriRepro intentionally does **not** run contributor-controlled pull-request code automatically. The repository has no ordinary `pull_request` or `pull_request_target` execution workflow. This avoids sending untrusted fork code either to persistent maintainer hardware or to a hosted CI service that the project does not rely on for release certification.

The contribution path is:

1. contributor opens a PR and provides local test evidence;
2. maintainer reviews the diff, workflow changes, dependency changes, and trust-boundary impact without executing the fork branch on persistent infrastructure;
3. the GitHub-hosted CI and validation workflows certify the merged `main` state;
4. accepted changes are merged through the protected maintainer flow first; the public GitHub-hosted validation workflow then certifies only an exact SHA reachable from canonical `main` and publishes sanitized evidence artifacts;
5. every release-facing source change receives fresh source-bound discovery/planning/ReproBench/certification-environment evidence from the GitHub-hosted validation workflow before release.

Do not ask maintainers to execute fork PR code on self-hosted or persistent hardware. If stronger adversarial contribution testing becomes necessary, it must use genuinely disposable GitHub-hosted isolation.

Real-paper and credentialed smoke workflows remain separate and maintainer-dispatched on GitHub-hosted runners. Their generated result files are transient and are not uploaded as GitHub Actions artifacts. Contributors do not need access to maintainer runners or credentials for ordinary pull requests.

The release-only PyPI Trusted Publishing workflow is not a contribution CI lane. It is triggered only by a published GitHub Release and keeps OIDC publication authority isolated from source validation.

Security-sensitive issues should follow `SECURITY.md` and use the repository's private Security advisory flow instead of being disclosed in a public issue.
