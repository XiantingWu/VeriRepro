# Release evidence

This page is the human-readable index for VeriRepro `0.8.0` evidence. It records what was actually measured, which source identity produced the measurements, and what the measurements do **not** prove.

## Evidence policy

XiantingWu/VeriRepro is a public repository. All certification measurement is executed on **GitHub-hosted runners only** through the public `VeriRepro validation` workflow. No maintainer-owned self-hosted runner, private runner label, or runner group is ever used for CI, validation, certification, or publishing.

This repository never claims a private certification chain as its own. Anything below marked **historical / imported** is carried from an earlier development line and is not current Xianting certification authority.

## Historical / imported evidence

An earlier development line also produced the following imported historical
provenance:

- `github_actions_run_id`: `32523314161`
- `head_sha`: `16044bec91ac1e94021c5ceace9700ad673463d8`
- ReproBench `source_tree_sha256`: `e25cacde58e3d0dcc56a8e38e23a4f71d1c94b87ee38c29364b7949460c56128`

These identifiers do **not** match the current Xianting `main`. They are
historical provenance records only and are superseded by the current
Xianting-native certification below.

## Previous Xianting-native certification (historical)

- Certified source: `84fcc6f24610d13124fc204055166b2b069c8297`
- Release-source SHA-256: `ef02b937193882f658a35d90da5a3dd60c212923c906ec4f7f1333b3dbee9ad2`
- Validation run: GitHub-hosted `VeriRepro validation` run `33276158764`
- Evidence commit: `027fe3c`

Discovery 15/15, planning 3/3, ReproBench 1 success / 1 partial / 0 failures — all produced on GitHub-hosted `ubuntu-latest` at the previous exact certified source. This certification is superseded by the P1 hardening source and is retained only as historical provenance.

## Previous Xianting-native certification (S1/F1, historical)

The previous Xianting-native authority was superseded by the final
supply-chain hardening round and remains an immutable historical record:

- Certified source: `ace6683ff24399ff374eec5c05669b67783ffec9`
- Release-source SHA-256: `4cc5f2d80af9f08a5720cfce273c0f0fe8f2e21af586fffad98f5c939af1b4b8`
- Validation run: GitHub-hosted `VeriRepro validation` run `33282504163`
- Evidence commit: `820898feec6fc4f663c45bf0a42216c64d434bee`
- Discovery: 15/15
- Planning: 3/3
- ReproBench: 1 success / 1 partial / 0 failures

Discovery 15/15, planning 3/3, and ReproBench 1 success / 1 partial / 0
failures were measured at the previous source identity. They are historical,
not the current certification authority.

## Current Xianting-native certification

The current Xianting-native authority is complete after the final release
supply-chain hardening round:

- Certified source (S2): `cd0c962cbf72ebcecea7f5e6af56b98c4d5576ef`
- Release-source SHA-256 (F2): `1032069218c9bbecaf8ec7eda6de48bf704e9552487a26ce828a19c6084d6569`
- Validation run: GitHub-hosted `VeriRepro validation` run `33316585656`
- Evidence commit (E2): `e262560c4be81b8de1f890ca0effc315b3d6b3f0`
- Evidence topology: the evidence-only promotion is a protected-main commit
  directly based on S2.
- Discovery: 15/15 expected repositories, 15/15 top-1, 15/15 evidence anchored
- Planning: 3/3 expected repositories, 3/3 top-1, 3/3 evidence anchored
- ReproBench: 1 success / 1 partial / 0 failures

The validation run tested the exact S2 source and recorded F2 in the sanitized
artifact. The artifact was reviewed and promoted through an explicit
evidence-only PR. The former S1/F1, validation run `33282504163`, and E1 are
retained as historical provenance; S2/F2, validation run `33316585656`, and E2
are current.

## Scientific limits

- A 15-paper discovery corpus, 3-repository environment planning, and 2-case ReproBench seed exercise certify only the tested gates and inputs.
- Discovery `15/15`, planning `3/3`, and ReproBench outcomes are only claimed as **current** after a fresh Xianting-native validation run confirms them.
- Hardware-dependent or private-network capabilities that GitHub-hosted infrastructure cannot execute are marked `NOT VERIFIED / DEFERRED` rather than simulated on self-hosted runners.

## Source fingerprint

The release-source fingerprint covers runtime/package code, exact certification
constraints, measurement and promotion policy, layered release checks,
public-launch policy, Dependabot/dependency-review policy, public
CI/validation/publish workflows, the typing marker, and release-only publish
workflow. Documentation and promoted evidence files are intentionally
excluded.

## Environment

Certification environment constraints are pinned exactly in `constraints/certification.txt`. The environment is resolved on GitHub-hosted `ubuntu-latest`; no host-specific machine identity is recorded.

## ReproBench interpretation

- `success`: paper result reproduced with independent evidence.
- `partial`: reproduction executed but outcome evidence incomplete.
- `failure`: reproduction failed to execute or contradicted the paper.

Outcomes are evidence states, not aliases for process exit codes.
