# Release evidence

This page is the human-readable index for VeriRepro `0.8.0` evidence. It records what was actually measured, which source identity produced the measurements, and what the measurements do **not** prove.

## Evidence policy

XiantingWu/VeriRepro is a public repository. All certification measurement is executed on **GitHub-hosted runners only** through the public `VeriRepro validation` workflow. No maintainer-owned self-hosted runner, private runner label, or runner group is ever used for CI, validation, certification, or publishing.

This repository never claims a private certification chain as its own. Anything below marked **historical / imported** is carried from an earlier development line and is not current Xianting certification authority.

## Historical / imported evidence

The benchmark files under `benchmarks/` currently contain measurements imported from an earlier development line:

- `github_actions_run_id`: `32523314161`
- `head_sha`: `16044bec91ac1e94021c5ceace9700ad673463d8`
- ReproBench `source_tree_sha256`: `e25cacde58e3d0dcc56a8e38e23a4f71d1c94b87ee38c29364b7949460c56128`

These identifiers do **not** match the current Xianting `main`. They are historical provenance records only and are superseded by fresh Xianting-native certification when it is produced.

## Current Xianting-native certification

- Certified source: **pending** (fresh certification is produced after the public CI/release control plane is stable)
- Release-source SHA-256: **pending**
- Validation run: **pending**
- Evidence commit: **pending**

Until a fresh certification run completes, do not cite `32523314161`, `16044bec…`, or `e25cacde…` as current certification.

## Scientific limits

- A 15-paper discovery corpus, 3-repository environment planning, and 2-case ReproBench seed exercise certify only the tested gates and inputs.
- Discovery `15/15`, planning `3/3`, and ReproBench outcomes are only claimed as **current** after a fresh Xianting-native validation run confirms them.
- Hardware-dependent or private-network capabilities that GitHub-hosted infrastructure cannot execute are marked `NOT VERIFIED / DEFERRED` rather than simulated on self-hosted runners.

## Source fingerprint

The release-source fingerprint covers runtime/package code, exact certification constraints, measurement and promotion policy, layered release checks, public-launch policy, public CI/validation/publish workflows, the typing marker, and release-only publish workflow. Documentation and promoted evidence files are intentionally excluded.

## Environment

Certification environment constraints are pinned exactly in `constraints/certification.txt`. The environment is resolved on GitHub-hosted `ubuntu-latest`; no host-specific machine identity is recorded.

## ReproBench interpretation

- `success`: paper result reproduced with independent evidence.
- `partial`: reproduction executed but outcome evidence incomplete.
- `failure`: reproduction failed to execute or contradicted the paper.

Outcomes are evidence states, not aliases for process exit codes.