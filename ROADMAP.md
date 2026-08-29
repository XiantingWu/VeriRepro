# Roadmap

VeriRepro is developed against measurable reproducibility, safety, and release gates rather than feature count. Roadmap items are phrased as observable capabilities so contributors can attach tests and evidence to them.

## Current public-beta candidate — 0.8

The 0.8 line establishes the first public release baseline.

### Evidence and reproduction semantics

- [x] evidence-grounded paper intelligence with page/quote verification;
- [x] repository-grounded execution planning and explicit abstention;
- [x] deterministic scalar, Figure, Table, and file evidence checks;
- [x] scientific `PASS`, `FAIL`, and `PARTIAL` remain distinct from process exit status;
- [x] repository-authored scientific expectations do not self-authorize verdicts;
- [x] real-paper discovery inputs are pinned and measured evidence is source-bound;
- [x] fresh 0.8 discovery/planning/ReproBench evidence has been regenerated from the certified release-source identity;
- [x] 15/15 release-corpus cases are source-evaluable, expected-repository found, top-1 correct, and evidence anchored;
- [x] bounded real-repository environment planning produces 3/3 plans;
- [x] the pinned CPU ReproBench seed executes with explicit intervention accounting and passes the release evidence gate.

### Runtime and trust boundaries

- [x] Git, Python, dependency, environment, dataset, model-artifact, and CUDA/GPU provenance;
- [x] Docker experiment execution with network disabled by default;
- [x] explicit non-root runtime identity and read-only root filesystem;
- [x] bounded writable `/workspace` and `/tmp` tmpfs overlays;
- [x] double authorization for experiment networking and GPU access;
- [x] bounded stdout/stderr capture and output indexing;
- [x] direct HTTPS, Hugging Face, and Zenodo dataset declarations;
- [x] checksum-bound dataset caching with sanitized provenance and concurrency controls;
- [x] checksum-bound model/checkpoint artifacts mounted read-only at runtime;
- [x] lock-aware uv, Poetry, conda-lock, and Pipenv environment realization;
- [x] optional bounded ephemeral `/repro-output` tmpfs for less-trusted output writers;
- [x] `doctor --strict` provides machine-readable pre-execution readiness.

### Public API and engineering

- [x] public package/CLI namespace `verirepro` with 0.x compatibility aliases and PEP 561 typing marker;
- [x] orchestration, deterministic policy, execution, verification, and reporting are separated behind the stable public API;
- [x] direct unit-test surfaces cover the major core modules plus a systematic failure matrix;
- [x] Ruff, mypy, statement/branch coverage, build, Twine, and clean-wheel installation are part of trusted Quality;
- [x] measured release-source coverage meets the 85% statement / 75% branch release floors;
- [x] external/fork pull requests run only on GitHub-hosted ephemeral runners with read-only permissions and no secrets;
- [x] reviewed contributions are certified on GitHub-hosted runners through the public validation workflow;
- [x] GitHub-hosted CI is the sole automated quality/validation lane;
- [x] layered package/workflow/benchmark/security release checks fail closed on public-surface and provenance regressions;
- [x] final release validation is GitHub-hosted, read-only, and produces sanitized evidence artifacts;
- [x] PyPI release workflow is designed around Trusted Publishing/OIDC and a protected environment.

Repository visibility, About metadata, private vulnerability reporting, and `main` protection are GitHub control-plane launch operations rather than missing runtime capabilities. They are tracked separately in `docs/PUBLIC_RELEASE_CHECKLIST.md`.

Release evidence is deliberately bounded. It demonstrates only the tested discovery, planning, build, execution, and evidence-integrity gates; it does not imply arbitrary-paper zero-configuration reproduction.

## 0.9 priorities

### Broader execution coverage

- [ ] validate NVIDIA/CUDA execution on dedicated NVIDIA-capable trusted infrastructure;
- [ ] add more repository/environment fixtures covering common modern scientific Python stacks;
- [ ] expand ReproBench beyond the initial seed while preserving immutable inputs, intervention accounting, and failure taxonomy;
- [ ] measure success, partial, and failure rates by domain instead of relying on anecdotal examples.

### Stronger hostile-code isolation

- [ ] add a rootless, VM-backed, or equivalently isolated dependency/image build backend;
- [ ] add a hard repository-transfer/checkout byte budget rather than relying only on shallow clone and downstream limits;
- [ ] continue reducing host-side parsing/build attack surface for intentionally adversarial inputs;
- [ ] add genuinely disposable Linux compatibility execution if contributor demand justifies automatic fork testing.

### Better scientific evidence

- [ ] improve automatic PDF Figure/Table crop-to-output matching;
- [ ] move beyond generic pixel similarity toward structure-aware and semantically constrained figure checks where deterministic semantics can be defined;
- [ ] expand machine-testable metric/tolerance policies without turning ambiguous metrics into false scientific PASS claims;
- [ ] improve explicit uncertainty reporting when papers omit reproduction-critical details.

### User and contributor experience

- [ ] simplify first-run diagnostics and remediation guidance across macOS and Linux;
- [ ] add more small, public, CPU-friendly end-to-end examples;
- [ ] keep report and manifest migrations documented as schemas evolve;
- [ ] improve contributor fixtures so trust-boundary changes can be tested without paid model calls or GPUs;
- [ ] add a short validated demo once it can be maintained without overstating scientific guarantees.

## 1.0 gate

VeriRepro should not call itself 1.0 until all of the following are true:

1. the public manifest schema has a documented compatibility and migration policy;
2. the public report JSON schema is stable and versioned;
3. a substantially broader real-paper benchmark is published with immutable inputs, transparent intervention accounting, and explicit limitations;
4. deterministic regression coverage exists for every documented trust boundary;
5. tagged GitHub releases and PyPI distributions are routine, reproducible, and protected by release-evidence/source-integrity gates;
6. no critical unresolved sandbox escape, host-network, credential-exposure, path-traversal, or unbounded host-read/write issue is known;
7. installation, first-run planning, execution preflight, security reporting, and contribution workflows work for an external user with no knowledge of the project's development history.

## Roadmap principles

- Missing evidence remains missing; it is never filled in merely to improve benchmark rates.
- A repository may describe how to run itself, but it may not silently grant itself scientific authority.
- Model output is a proposal, not an execution or evidence authority grant.
- Security limits are host-owned and fail closed.
- Benchmark growth must not weaken evidence quality, intervention accounting, or failure semantics.
- New capabilities should arrive with deterministic tests, public fixtures when practical, and an explicit statement of any new network/filesystem/credential/execution authority.

For current measured evidence see `docs/EVIDENCE.md`. For trust boundaries see `SECURITY.md` and `docs/TRUST_MODEL.md`. For release procedures see `docs/PUBLISHING.md`.
