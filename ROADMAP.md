# Roadmap

VeriRepro is developed against measurable reproducibility, safety, and release gates rather than feature count. Roadmap items are intentionally phrased as observable capabilities so contributors can attach tests and evidence to them.

## Current public beta — 0.8

The 0.8 line establishes the first public release baseline:

- [x] evidence-grounded paper intelligence with page/quote verification;
- [x] repository-grounded execution planning and explicit abstention;
- [x] Git, Python, dependency, environment, dataset, model-artifact, and CUDA/GPU provenance;
- [x] Docker experiment execution with network disabled by default;
- [x] explicit non-root runtime identity and read-only root filesystem;
- [x] bounded writable `/workspace` and `/tmp` tmpfs overlays;
- [x] double authorization for experiment networking and GPU access;
- [x] host-bounded stdout/stderr capture and output indexing;
- [x] deterministic scalar, Figure, Table, and file evidence checks;
- [x] direct HTTPS, Hugging Face, and Zenodo dataset declarations;
- [x] checksum-bound dataset caching with sanitized provenance and concurrency controls;
- [x] checksum-bound model/checkpoint artifacts mounted read-only at runtime;
- [x] lock-aware uv, Poetry, conda-lock, and Pipenv environment realization;
- [x] optional bounded ephemeral `/repro-output` tmpfs for less-trusted output writers;
- [x] public package/CLI namespace `verirepro` with 0.x compatibility aliases;
- [x] public fork CI isolated on GitHub-hosted runners without repository secrets;
- [x] version-matched release evidence for a pinned 15-paper discovery corpus, bounded 3-repository environment planning, and ReproBench seed cases;
- [x] PyPI release workflow designed around Trusted Publishing/OIDC and a protected environment.

The 0.8 release evidence is deliberately bounded. It demonstrates the tested discovery, planning, build, execution, and evidence-integrity gates; it does not imply arbitrary-paper zero-configuration reproduction.

## 0.9 priorities

### Broader execution coverage

- [ ] validate NVIDIA/CUDA execution on dedicated NVIDIA-capable trusted infrastructure;
- [ ] add more repository/environment fixtures covering common modern scientific Python stacks;
- [ ] expand ReproBench beyond the initial seed while preserving immutable inputs, explicit intervention accounting, and failure taxonomy;
- [ ] measure success, partial, and failure rates by domain instead of relying on anecdotal examples.

### Stronger hostile-code isolation

- [ ] add a rootless, VM-backed, or equivalently isolated dependency/image build backend;
- [ ] add a hard repository-transfer/checkout byte budget rather than relying only on shallow clone and downstream limits;
- [ ] continue reducing host-side parsing/build attack surface for intentionally adversarial inputs.

### Better scientific evidence

- [ ] improve automatic PDF Figure/Table crop-to-output matching;
- [ ] move beyond generic pixel similarity toward structure-aware and semantically constrained figure checks where deterministic semantics can be defined;
- [ ] expand machine-testable metric/tolerance policies without turning ambiguous metrics into false scientific PASS claims;
- [ ] improve explicit uncertainty reporting when papers omit reproduction-critical details.

### User and contributor experience

- [ ] simplify first-run diagnostics and remediation guidance across macOS and Linux;
- [ ] add more small, public, CPU-friendly end-to-end examples;
- [ ] keep report and manifest migrations documented as schemas evolve;
- [ ] improve contributor fixtures so trust-boundary changes can be tested without paid model calls or GPUs.

## 1.0 gate

VeriRepro should not call itself 1.0 until all of the following are true:

1. the public manifest schema has a documented compatibility and migration policy;
2. the public report JSON schema is stable and versioned;
3. a substantially broader real-paper benchmark is published with immutable inputs, transparent intervention accounting, and explicit limitations;
4. deterministic regression coverage exists for every documented trust boundary;
5. tagged GitHub releases and PyPI distributions are routine, reproducible, and protected by release-evidence/source-integrity gates;
6. no critical unresolved sandbox escape, host-network, credential-exposure, path-traversal, or unbounded host-read/write issue is known;
7. installation, first-run planning, execution preflight, security reporting, and contribution workflows are documented for an external user who has no knowledge of the project's development history.

## Roadmap principles

- Missing evidence remains missing; it is never filled in merely to improve benchmark rates.
- A repository may describe how to run itself, but it may not silently grant itself scientific authority.
- Model output is a proposal, not an execution or evidence authority grant.
- Security limits are host-owned and fail closed.
- Benchmark growth must not weaken evidence quality, intervention accounting, or failure semantics.
- New capabilities should arrive with deterministic tests, public fixtures when practical, and an explicit statement of any new network/filesystem/credential/execution authority.

For current security boundaries and known residual risks, see `SECURITY.md` and `docs/TRUST_MODEL.md`. For release procedures, see `docs/PUBLISHING.md`.
