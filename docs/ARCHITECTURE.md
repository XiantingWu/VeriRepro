# Architecture

VeriRepro 0.8 is an evidence-first orchestration layer for computational paper reproduction. It deliberately separates **proposal**, **verification**, **host authority**, **scientific evidence authority**, **benchmark authority**, and **experiment execution authority**.

## End-to-end pipeline

1. **Source resolution** — normalize arXiv IDs/URLs, DOI/doi.org URLs, PDF URLs, and local PDFs. Remote PDFs use HTTPS-by-default, public-address/redirect validation, a host-owned byte ceiling, and atomic materialization.
2. **Page-preserving extraction** — extract PDF text per page so claims can be checked against explicit page boundaries.
3. **Deterministic artifact discovery** — discover GitHub and dataset links directly from paper text/PDF annotations and rank repositories using bounded evidence proximity rather than raw occurrence order.
4. **Paper intelligence** — optionally ask a configured OpenAI-compatible model endpoint for structured experiment facts, metrics, repositories, and ambiguities.
5. **Evidence verification** — verify model-proposed quotes against the claimed PDF page. Claims become `verified`, `approximate`, or `unverified`.
6. **Ambiguity audit** — preserve missing reproduction-critical details instead of filling them with model guesses.
7. **Repository acquisition** — accept canonical HTTPS GitHub repository URLs, validate refs, disable Git `file`/`ext` transports and Git LFS smudge, and perform shallow no-tag operations.
8. **Repository inspection** — resolve an exact Git commit; inspect only real, non-symlink files contained by the clone root; detect Python/dependency/lockfile/CUDA signals; fingerprint the repository; and locate a preferred `verirepro.yaml` manifest or compatibility alias.
9. **Repository-grounded execution planning** — when an explicit command is absent, choose only among real repository entrypoints and accept a plan only after documentation/evidence/syntax validation.
10. **Environment planning** — resolve and validate a supported Python minor, dependency strategy, lock-aware realization, warnings, reproducibility grade, and environment fingerprint before image construction.
11. **Dataset materialization** — download only declared datasets under host-owned URL, redirect, path, count, byte, checksum, cache, and provenance policy.
12. **Model/checkpoint materialization** — resolve checksum-bound external model artifacts on the host, record sanitized provenance, and prepare them for a read-only `/models` mount.
13. **Environment image build** — construct the dependency/runtime image. This is a separate trust boundary from the final research-code runtime because third-party build hooks may execute and Docker-daemon access is not rootless by default.
14. **Sandboxed experiment execution** — run third-party research code inside Docker with explicit non-root identity, read-only root filesystem, bounded writable tmpfs overlays, dropped capabilities, `no-new-privileges`, PID/CPU/memory limits, and network/GPU access only after independent host authorization.
15. **Output handling** — expose `/repro-output` as either a persistent run-scoped host bind or an operator-selected bounded ephemeral tmpfs; index retained outputs under host-owned read/entry/file limits and refuse symlinks.
16. **Metric verification** — compare reproduced scalar metrics only when paper-grounded or explicitly host-authorized scientific expectations define deterministic comparison semantics.
17. **Figure/Table/file verification** — compare explicitly declared reference/reproduced artifact pairs only after scientific-contract authorization; undeclared files remain inventory, not scientific evidence.
18. **Reporting** — write Markdown plus `report.json` schema version 1, evidence payloads, environment/repository plans, dataset/model provenance, logs, artifact results, and output inventory.
19. **ReproBench adaptation** — map a versioned benchmark task through the normal VeriRepro pipeline and emit a sanitized result contract containing outcome, deterministic stage/metric/artifact measurements, provenance, operator interventions, model-usage telemetry when available, and failure taxonomy.

## Authority model

### Execution authority

A reproduction command is selected in this order:

1. explicit user `--command`;
2. `verirepro.yaml` / `.verirepro.yaml` (legacy `reproagent.yaml` aliases remain supported);
3. a model-assisted repository plan that passes deterministic repository evidence and command validation;
4. a recognized conventional entrypoint such as `reproduce.py`.

Model output never bypasses these checks. Repository commands execute inside the restricted experiment container rather than directly on the host.

### Scientific evidence authority

A repository may describe how it should run, but it does not automatically get to define the scientific truth used to certify itself.

Repository-authored metrics and reference artifacts remain outside PASS/FAIL by default. They enter scientific comparison only after explicit host authorization through `--trust-repository-contract` or the equivalent trusted API setting. Automatically extracted paper metrics must separately satisfy page/quote grounding plus VeriRepro's deterministic metric/tolerance policy.

A successful process exit is therefore not equivalent to a scientific `PASS`; a run can remain `PARTIAL` when execution succeeds but independent scientific evidence is insufficient.

## Trust boundaries

### Remote paper acquisition

Remote PDF URLs are host-side network input. VeriRepro rejects embedded credentials and non-public destinations, re-validates redirects, applies a host-owned byte limit, and writes through an atomic temporary file before parsing.

### Paper text and model output

PDF text is untrusted data. Prompt-like content inside a paper is never treated as an instruction. Model proposals are accepted only after deterministic evidence, repository-membership, entrypoint, documentation, and command checks appropriate to the proposal type.

### Repository acquisition and inspection

Repository source is untrusted before Docker exists. Cloning is limited to canonical HTTPS GitHub repositories, refs are validated, dangerous Git transports and automatic LFS materialization are disabled, and host inspection refuses symlinked inputs. Manifests are size-bounded regular files parsed with YAML safe loading.

### Host-side downloads

Repository declarations can influence host-side dataset/model retrieval, so download policy is a separate trust boundary. Provider validation, address checks, redirect checks, host-owned count/byte budgets, destination confinement, atomic writes, symlink refusal, checksum verification, and sanitized provenance reduce risk. Infrastructure egress controls remain recommended for hostile inputs.

### Build boundary

Dependency/image construction may execute third-party package-manager or build hooks and may need package-index network access. Runtime non-root/read-only controls do not make the Docker build or daemon rootless. Adversarial builds require additional disposable or rootless infrastructure.

### Third-party experiment runtime

The final research-code container uses:

- explicit non-root UID:GID;
- read-only root filesystem;
- sealed repository image template copied into bounded writable `/workspace` tmpfs;
- bounded `/tmp` tmpfs;
- read-only `/datasets` and `/models` mounts;
- dropped Linux capabilities and `no-new-privileges`;
- init, PID, CPU, and memory limits;
- unique container names and bounded timeout cleanup;
- host-bounded stdout/stderr capture;
- network disabled unless both repository request and user `--allow-network` authorization are present;
- GPU devices unavailable unless both repository request and user `--allow-gpu` authorization are present;
- no model-provider credentials inside the experiment container.

Docker is an isolation layer, not a formal sandbox proof. Intentionally hostile code should additionally use an ephemeral VM, rootless runtime, or hardened sandbox.

### Artifact paths and outputs

Reference paths are confined to the cloned repository and reproduced paths to the run output root. Output indexing refuses symlinks and applies host-owned entry/file/per-file/cumulative-read budgets. Figure/Table/file comparison adds independent byte/cell/pixel limits. Arbitrary output files do not become PASS/FAIL evidence.

### ReproBench task/result boundary

Benchmark task JSON is untrusted data with narrower authority than an interactive user invocation. It cannot request local paper files, insecure HTTP sources, embedded credentials, path traversal, or arbitrary executable fields. Unknown task fields are bounded and recorded but not interpreted.

Result JSON removes free-form stage details and host workspace paths before aggregation. Operator overrides remain explicit interventions rather than hidden autonomous success. Outcome/failure-taxonomy consistency is machine-validated both during aggregation and again by final release checks.

### Secrets

Model-provider credentials remain host-side and are not injected into experiment containers. Hugging Face authorization is scoped to the initial Hugging Face host and stripped on cross-host redirects. Release evidence excludes endpoint URLs, credentials, prompts, responses, private host paths, and raw experiment workspaces.

## Machine-readable contracts

- Manifest schema: version 1; preferred filenames are `verirepro.yaml` / `.verirepro.yaml`, with legacy aliases during the 0.x compatibility window.
- Report schema: `report.json` contains `schema_version: 1`.
- ReproBench task schema: version 1.
- ReproBench result schema: version 1.
- ReproBench summary schema: version 1.
- Public verdicts: `PASS`, `FAIL`, `PARTIAL`.
- Generated artifact directory: `VERIREPRO_OUTPUT_DIR` (legacy alias exported in parallel).
- Dataset mount: `VERIREPRO_DATASET_DIR` (legacy alias exported in parallel).
- Model-artifact mount: `VERIREPRO_MODEL_DIR` (legacy alias exported in parallel).
- Preferred scalar metric prefix: `VERIREPRO_METRIC` (legacy prefix accepted during the compatibility window).

See `SCHEMAS.md`, `REPROBENCH.md`, and `TRUST_MODEL.md` for compatibility and trust details.

## Release-check boundaries

`scripts/release_check.py` is a thin aggregator. Each gate lives in an independently testable module under `scripts/release_checks/`:

- `common.py`: shared file inventory, safe path handling, command-gate helpers.
- `package_surface.py`: distribution metadata, version alignment across namespaces, canonical repository URLs.
- `security_surface.py`: trust-boundary declarations in `SECURITY.md`, private advisory routing, historical-incubator rejection.
- `workflow_surface.py`: workflow trigger/runner-label contracts, GitHub-hosted fork-PR isolation, resource bounds, action pinning, publish-workflow safety.
- `public_contract_surface.py`: current public contribution, certification, evidence-promotion, and delivery language.
- `benchmark_surface.py`: smoke corpus and release-evidence structure checks.

Every check appends human-readable errors and fails closed: any error fails the entire release check, and missing files are failures rather than skips. The layers are exercised directly by `tests/test_release_check_layers.py`.

## Release evidence lifecycle

1. Freeze a candidate canonical `main` SHA.
2. Dispatch `VeriRepro validation` against that exact canonical source identity.
3. Validation runs deterministic quality, discovery, planning, ReproBench, and environment checks on a GitHub-hosted runner.
4. The workflow uploads only the sanitized evidence artifact; it does not modify a branch.
5. The maintainer verifies source SHA, run ID, fingerprint, and evidence purity.
6. Create an evidence branch from the certified source.
7. Commit only version-matched benchmark evidence.
8. Review and merge an explicit evidence-only PR.
9. `release_source_check.py` revalidates source/evidence identity at publication time.

If runtime code, release scripts, or workflow policy change after certification, existing evidence is stale and must be regenerated from a new exact canonical `main` SHA.

## Package and integration boundaries

The standalone package exposes the `verirepro` namespace and compatibility `reproagent` aliases during the 0.x series. Runtime code does not depend on unpublished sibling-project source trees.

Cross-project benchmark or agent integration uses versioned JSON, CLI/process boundaries, report schemas, or published packages instead of hidden relative imports.

External/fork pull requests use GitHub-hosted fork-PR isolation only: read-only, secret-free, no self-hosted runners, and no `pull_request_target`. Maintainers review the diff and merge through the protected `main` flow; the exact canonical `main` SHA is then certified by the public GitHub-hosted `VeriRepro validation` workflow. Final trusted benchmark evidence and source-fingerprint checks remain release gates and are enforced again before publication.
