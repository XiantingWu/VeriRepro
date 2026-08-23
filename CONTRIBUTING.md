# Contributing

Contributions should improve **measurable scientific reproducibility**, not just increase agent complexity.

## Setup

```bash
python -m pip install -e '.[dev]'
pytest -q
verirepro --version
verirepro doctor --json
python scripts/release_check.py
python scripts/launch_surface_check.py
```

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
10. Public pull-request CI must remain safe for untrusted forks: GitHub-hosted workers only, no repository secrets, and no persisted checkout credentials. Networked/credentialed smoke belongs in maintainer-controlled workflows.

## Pull requests

A useful PR explains:

- the reproducibility failure mode it addresses;
- the deterministic evidence contract;
- tests or a public minimal fixture;
- any new network/filesystem/credential/execution authority;
- backwards-compatibility impact on the manifest or report schema.

Run the full local suite before opening a PR:

```bash
pytest -q
verirepro doctor --json
python scripts/release_check.py
python scripts/launch_surface_check.py
```

### Public fork PRs

External fork pull requests receive the same unit, release-tree, launch-surface, distribution-build, Twine, and clean-wheel-install checks on GitHub-hosted ephemeral runners. That workflow receives no repository secrets and does not execute fork code on maintainer hardware.

Real-paper and LiteLLM smoke workflows are deliberately separate and maintainer-dispatched on trusted integration infrastructure. Contributors do not need access to maintainer runners or credentials for ordinary pull requests.

Security-sensitive issues should follow `SECURITY.md` and use the repository's private Security advisory flow instead of being disclosed in a public issue.
