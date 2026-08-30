# Support

VeriRepro separates normal usage help, reproducibility debugging, bugs, feature proposals, and security reports so each can be handled with the right evidence and disclosure level.

## Reproduction help

Use the **Reproduction help** issue form when a paper/repository does not plan or reproduce as expected but you are not yet sure whether the behavior is a software defect.

Useful information includes:

- the paper reference (arXiv ID/URL, DOI, or public PDF URL);
- the stage that stopped or produced an unexpected result;
- the exact sanitized command;
- `verirepro --version`;
- sanitized `verirepro doctor --json` output;
- relevant stage names/statuses from `report.json` or a short report excerpt;
- operating system, Python version, and Docker availability when execution is involved.

Do not post API keys, access tokens, private repository URLs, private endpoint URLs, unpublished paper content, or sensitive dataset/model URLs.

## Bugs

Use the **Bug report** issue form for a minimal, reproducible VeriRepro defect. Please distinguish a software failure from an upstream research repository or dependency that is unavailable, underspecified, or non-reproducible.

## Feature requests

Use the **Feature request** form for changes to supported paper sources, environment strategies, evidence semantics, sandbox controls, artifact comparison, schemas, APIs, or contributor tooling.

For trust-boundary changes, describe any new network, filesystem, credential, model, dataset, GPU, or execution authority the feature would introduce.

## Security reports

Do **not** open a public issue for credentials, sandbox escapes, SSRF, path traversal, unsafe repository execution, secret exposure, or another security-sensitive finding.

Use the repository's private Security advisory flow:

`https://github.com/XiantingWu/VeriRepro/security/advisories/new`

See `SECURITY.md` for scope and the documented residual risks.

## Contribution questions

Before proposing code, read `CONTRIBUTING.md`. External PRs receive GitHub-hosted secret-free CI, but they do not receive certification authority. Only merged canonical `main` may be certified by the manual GitHub-hosted validation workflow. Sanitized evidence is promoted through an explicit evidence-only PR.

## What support cannot promise

VeriRepro cannot make an unavailable dataset, vanished dependency, incompatible historical GPU stack, undocumented training procedure, or incomplete paper specification reproducible by inference alone. Missing evidence remains missing and should be reported as such rather than replaced with guesses.
