# Canonical project identity

The canonical public VeriRepro source repository is:

**https://github.com/XiantingWu/VeriRepro**

The canonical Python distribution name is `verirepro`, and the preferred CLI and Python import namespace are also `verirepro`.

Repositories, mirrors, copies, or similarly named projects under other GitHub owners are **not canonical VeriRepro release authorities unless this document explicitly lists them**. At present, no external mirror is designated as canonical or release-authoritative.

For release and security decisions, verify all of the following together:

- repository owner/name: `XiantingWu/VeriRepro`;
- package metadata URLs point back to that repository;
- release evidence passes `scripts/release_check.py --require-release-evidence`;
- release-source identity passes `scripts/release_source_check.py`;
- all GitHub Actions workflows execute on GitHub-hosted runners only;
- stable PyPI publication, when enabled, uses the `verirepro` project and the repository's protected Trusted Publishing path.

A source-compatible copy can reproduce the code bytes while still being a different distribution authority. GitHub stars, repository names, or copied README text are not authority signals.