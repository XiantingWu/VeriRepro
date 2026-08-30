# Changelog

Notable user-facing changes are recorded here. Internal CI incidents and one-off maintainer infrastructure details are intentionally omitted from public release notes.

## 0.8.2 — public release truth and metadata correction

- synchronize public release-status documentation;
- make PyPI installation the primary user path;
- correct stale PyPI-facing README metadata through a new immutable package version;
- refresh current release evidence after fresh source-bound certification;
- no intentional scientific runtime or public API semantics change.

## 0.8.1 — release-delivery correction

- correct the PyPI Trusted Publishing action pin so the v1.14.2 annotated
  upstream tag is pinned by its dereferenced release commit rather than its
  tag-object SHA;
- add regression coverage for annotated GitHub Action tag dereferencing;
- add release validation of the exact PyPI action container image before a
  candidate is certified;
- no scientific runtime, reproduction semantics, or public API behavior is
  intentionally changed by this patch;
- the v0.8.0 GitHub release completed, but its first PyPI delivery did not
  upload distributions because the publishing action used an annotated tag
  object SHA without a corresponding runtime image.
- production PyPI Trusted Publishing subsequently completed successfully
  through the protected GitHub environment;
- clean installation from pypi.org was independently verified.

## 0.8.0 — hardened runtime, verification, and release engineering

0.4–0.7 were pre-public development milestones; 0.8.0 is the first planned stable public package publication.

- add lock-aware environment realization for uv, Poetry, conda-lock, and Pipenv while reporting unlocked solve paths as potentially drift-prone;
- add explicit GPU double authorization: repository request plus independent operator `--allow-gpu`; CUDA hints never grant devices;
- add checksum-bound, concurrency-hardened host dataset caching with sanitized provenance and fail-safe lock contention;
- run experiment commands as an explicit non-root UID:GID and fail closed rather than falling back to container root;
- seal repository source into the image, run the final research-code container with a read-only root filesystem, and provide bounded non-root writable `/workspace` and `/tmp` tmpfs overlays;
- add checksum-bound model/checkpoint declarations with hardened host retrieval, public Hugging Face/Zenodo resolution, sanitized provenance, and read-only `/models` mounts;
- add optional bounded ephemeral `/repro-output` tmpfs for less-trusted output writers while retaining persistent run-scoped output as the compatibility default;
- add `verirepro doctor --strict` and optional `--require-llm` for secretless machine-actionable readiness checks;
- split the reproduction pipeline into orchestration, deterministic policy, execution, verification, and reporting layers while preserving the public `reproduce()` contract;
- split release validation into package/public, workflow/publishing, benchmark/provenance, and security policy layers behind the stable `check_release_tree()` entry point;
- add direct unit-test surfaces for datasets, environment, discovery, experiment, metrics, intelligence, and pipeline layers plus a systematic failure matrix for malformed/timeout inputs, repository/dataset/runtime failures, malformed model output, and missing/mismatched result evidence;
- add branch-coverage measurement, exact-SHA certification, Ruff/mypy checks, release/launch gates, distribution build, Twine validation, and clean-wheel installation on GitHub-hosted runners;
- run external/fork pull requests only on GitHub-hosted ephemeral runners with read-only permissions and no secrets;
- require every CI, validation, and certification job to run on GitHub-hosted runners only; no workflow may use self-hosted runners, private runner labels, or runner groups;
- declare the preferred `verirepro` package as PEP 561 typed and verify the installed wheel carries `py.typed`;
- make `verirepro` the explicitly tested long-term public API while retaining `reproagent` as the 0.x compatibility/implementation namespace;
- add canonical standalone package/repository metadata, public launch-surface validation, dependency-update automation, and stable-only PyPI publication through Trusted Publishing/OIDC;
- require fresh version-matched discovery, environment-planning, and ReproBench evidence from the final release-source identity; historical 0.8 measurements cannot certify a source or release-policy tree changed after measurement;
- bind runtime/package code, release-policy layers, typing marker, and trusted certification/publish workflows into release-source provenance so stale evidence fails closed after release-relevant changes;
- bind an exact maintainer certification dependency snapshot and sanitized resolved-environment record into release provenance while retaining compatible end-user dependency ranges;
- add benchmark-owned host scientific artifact contracts, SHA-256-bound references, and selected-column table comparison so third-party repositories cannot self-authorize scientific success;
- require 0.8+ release evidence to include at least one grounded scientific ReproBench success while preserving evidence-limited `PARTIAL` outcomes;
- keep the sealed repository template read-only while restoring owner-only write permission on the ephemeral runtime workspace copy, allowing legitimate experiments to update tracked result files without weakening non-root/read-only-root isolation;
- preserve default-deny experiment networking, dropped capabilities, `no-new-privileges`, PID/CPU/memory limits, bounded logs/output processing, and scientific evidence-authority separation;
- document remaining limits explicitly: NVIDIA hardware is not yet release-certified, Git checkout has no hard transfer/working-tree byte quota, persistent output has no portable hard write quota, and hostile dependency/image builds require stronger isolation than the final Docker runtime boundary.

## 0.7.0 — ReproBench end-to-end evidence boundary

- add a versioned ReproBench task/result JSON adapter and public `verirepro.reprobench`, `verirepro-reprobench`, and `verirepro-reprobench-summary` interfaces;
- treat benchmark task/result data as untrusted with byte caps, symlink refusal, strict JSON, source/path confinement, and bounded unknown fields;
- record environment build, experiment execution, grounded metric/artifact comparisons, expected-artifact coverage, runtime, deterministic failure taxonomy, and explicit operator interventions;
- enforce outcome/taxonomy consistency so hard infrastructure or scientific failures cannot be hidden behind `partial`;
- make required pre-execution failures fail closed and keep repository absence as a hard pipeline failure;
- isolate concurrent reproduction workspaces so same-paper runs cannot share outputs or evidence;
- harden dataset destinations, Python-minor validation, Docker build/runtime log capture, timed-out container cleanup, output indexing, and Figure/Table/file verification budgets;
- bound repository-discovery work before ranking/model-context expansion;
- add context-local LiteLLM benchmark telemetry with a fixed non-secret whitelist and no inferred pricing;
- add a bounded CPU ReproBench seed suite with immutable repository commit pins and explicit interventions;
- keep successful process execution distinct from scientific PASS when independent scientific evidence is absent;
- bind release evidence to exact suite/task/result/summary bytes and the deterministic release-source fingerprint;
- require version-matched discovery/planning/ReproBench evidence for the release rather than reusing prior-version measurements after source changes;
- add standalone export symlink protection and final committed-evidence/source-fingerprint release gates.

## 0.6.0 — pinned real-paper corpus and planning evidence

- expand the pinned discovery corpus from 5 to 15 public papers across vision, NLP, dynamical systems, differentiable physics, scientific ML/PDE, and quantum-computing domains;
- require deterministic expected-repository discovery, correct top-1 ranking, and evidence anchors across the release corpus;
- bind results to exact corpus bytes with SHA-256 and explicit arXiv revision pins;
- separate source/infrastructure failures from evaluable algorithm-quality failures;
- add bounded real-repository environment-planning measurements without executing third-party commands;
- add explicit model-assisted planning measurements with safe-command, abstention, and blocking-failure outcomes;
- record bounded LiteLLM request/model/token/runtime/provider-cost telemetry when available while excluding endpoints and credentials;
- tighten automatic scientific scalar authority around supported metric classes, deterministic tolerances, grounded evidence, and explicit experiment metric markers.

## 0.5.0 — public VeriRepro surface

- adopt **VeriRepro** as the public project/package/CLI/Python-import name while retaining `reproagent` compatibility aliases during 0.x;
- support `import verirepro` and `python -m verirepro`;
- add preferred `VERIREPRO_LITELLM_*`, output, dataset, and metric-marker names while preserving compatibility aliases;
- add Hugging Face and Zenodo dataset providers and harden host retrieval with HTTPS/public-address/redirect/size/path/checksum controls;
- harden remote PDF retrieval and canonical GitHub repository acquisition;
- refuse symlinked host-inspection inputs and bound manifest parsing;
- add explicit `report.json` schema versioning and manifest compatibility policy;
- add Figure/Table/file verification, output provenance, and stricter scientific evidence authority;
- strengthen Docker runtime defaults with dropped capabilities, `no-new-privileges`, init, PID/CPU/memory limits, and default network isolation;
- add public packaging metadata, license/security/contribution/citation files, issue/PR templates, standalone export validation, and PyPI Trusted Publishing workflow design.

## 0.4.0

- add declarative Figure/Table/file artifact contracts;
- index generated outputs with SHA-256 provenance;
- compare normalized images deterministically;
- compare CSV/TSV tables with explicit absolute/relative numeric tolerances;
- integrate artifact verification into PASS/FAIL/PARTIAL verdicts;
- constrain reference and reproduced artifact paths to their allowed roots.

## 0.3.0

- rank repository candidates using evidence context;
- add repository-grounded execution planning with a constrained Python/Jupyter command validator;
- require repository documentation to support planned commands and reject unsafe shell syntax/undocumented arguments;
- require double opt-in experiment networking: repository request plus explicit user `--allow-network`;
- record exact Git commit and support `--ref` pinning;
- detect Python requirements, dependency strategies, and CUDA/GPU signals;
- generate repository/environment fingerprints and `environment-plan.json`;
- add `analyze`, `inspect`, and `doctor` CLI workflows;
- make Docker availability checks fail closed on timeout/socket errors;
- add artifact discovery, repository plan, and environment provenance to reports.

## 0.2.0

- add evidence-grounded LiteLLM paper intelligence;
- verify page/quote evidence;
- add ambiguity audit and grounded metric extraction;
- add repository-grounded execution planning with strict command validation.

## 0.1.0

- initial paper resolution, repository discovery, Docker execution, metric comparison, and reproducibility report.
