# Security policy

Do not place API keys, private paper contents, private repository URLs, unpublished datasets, or credentials in public issues or logs.

VeriRepro processes untrusted remote paper URLs, PDFs, model output, third-party repositories, host-side dataset URLs, build output, and experiment output. Current controls include:

- host-side remote PDF protection: HTTPS by default, no embedded credentials, DNS/IP checks against non-public destinations, redirect re-validation, a host-owned PDF byte ceiling, and atomic partial files;
- page/quote evidence verification for paper claims;
- deterministic repository discovery/allow-listing from observed paper evidence;
- GitHub-only HTTPS repository cloning, conservative ref validation, and Git `file`/`ext` protocol denial;
- host-side repository inspection that refuses symlinked dependency files, manifests, source files, notebooks, and metadata instead of following them outside the clone root;
- a 1 MiB manifest parsing limit and YAML safe loading;
- repository-grounded command planning with entrypoint, documentation-evidence, and shell-syntax validation;
- rejection of shell chaining, redirects, command substitution, control/newline separators, invented entrypoints, package managers, network utilities, and undocumented flags in model-generated plans;
- explicit Python-minor validation before a requested/inferred version can enter a generated Dockerfile;
- Docker isolation for experiment execution;
- explicit non-root experiment identities: the runtime always passes Docker `--user`; an already-non-root host UID/GID is mapped into the container, while a host UID 0 is remapped to fixed unprivileged `65532:65532` or fails closed if the run-scoped output directory cannot be prepared;
- `HOME=/tmp` for arbitrary numeric runtime users, avoiding implicit `/root` dependence;
- the installed repository is sealed as an image template under `/opt/verirepro-repository`; runtime uses Docker `--read-only`, copies that template into a host-budgeted non-root `/workspace` tmpfs, and uses a separate bounded `/tmp` tmpfs;
- runtime capability dropping, `no-new-privileges`, a PID limit, CPU/memory limits, and an init process;
- unique experiment-container names plus bounded timeout cleanup: a timeout attempts `docker rm -f`, stops the attached client, retries cleanup once, and never claims cleanup succeeded unless Docker confirms the remove;
- bounded host capture of experiment stdout/stderr (8 MiB per stream by default, configurable only by the host with `VERIREPRO_MAX_EXPERIMENT_LOG_BYTES`) while continuing to drain child pipes; the final tail is retained so terminal `VERIREPRO_METRIC` evidence is not lost behind verbose training logs;
- bounded host capture of Docker build stdout/stderr (8 MiB per stream by default, configurable only by the host with `VERIREPRO_MAX_DOCKER_BUILD_LOG_BYTES`), retaining the final diagnostic tail instead of buffering arbitrary third-party build output in Python memory;
- double opt-in experiment networking: a repository may request network access, but the user must separately authorize `--allow-network`;
- double opt-in GPU device access: a repository may request GPU access, but the user must separately authorize `--allow-gpu`; CUDA/GPU detection never grants devices by itself;
- separation of LiteLLM credentials from experiment containers;
- namespace-aware API-key selection so an unrelated `OPENAI_API_KEY` is not forwarded to a separately configured LiteLLM gateway;
- artifact-path confinement for repository references and generated outputs;
- host-side output indexing that refuses symlinks and applies host-owned entry-count, file-count, per-file-byte, and cumulative-read budgets before hashing untrusted outputs;
- host-side Figure/Table/file verification budgets: bounded comparison bytes, bounded table bytes/cell counts, and bounded image pixels; safety-budget violations become explicit failed stages instead of uncaught host exceptions;
- host-side dataset download protection: HTTPS by default, no embedded credentials, DNS/IP checks against non-public destinations, redirect re-validation, host-owned byte/count ceilings, bounded single-component destination filenames, duplicate-target refusal, output/temp path confinement, atomic partial files, optional SHA-256 verification, symlink refusal, and cross-host authorization stripping;
- optional cross-run dataset caching is host-owned and checksum-bound: only declarations with a valid SHA-256 are reusable, every cache hit is rehashed before materialization, cache roots/entries use path and no-follow checks, and cache entry/byte budgets are host-owned;
- cooperating shared-cache writers serialize cache reads/stores and capacity decisions under a bounded advisory lock; same-digest stores are idempotent, the lock file is excluded from cache entry accounting, and ordinary lock contention falls back to uncached download rather than accepting unverified bytes;
- dataset provenance records sanitized source identity, observed/expected SHA-256, bytes, materialization source, and cache outcome without persisting credentials, URL query strings, or host cache paths;
- model/checkpoint artifacts require SHA-256, are materialized through the hardened host download path, record sanitized provenance, and are mounted read-only at `/models` without forwarding model-hub credentials into the experiment container;
- operators may choose bounded ephemeral output: `/repro-output` becomes a host-sized non-root tmpfs with no host bind, so file outputs are discarded at container exit and over-budget writes fail inside the disposable volume.

A repository cannot self-enable experiment networking or GPU access merely by committing those requests to a manifest. It also cannot raise the host dataset, cache, output-processing, or artifact-verification ceilings from repository content. Higher host budgets require explicit host environment configuration.

The non-root/read-only runtime applies to the final research-code container. It is not a claim that the Docker daemon, image build, dependency installation, or host process is rootless. `/workspace` and `/tmp` are explicit bounded tmpfs overlays, `/datasets` and `/models` are read-only, and `/repro-output` is either the persistent run-scoped bind or an operator-selected bounded ephemeral tmpfs.

## Public pull requests and validation isolation

This repository intentionally ships without GitHub Actions workflows. Unit tests, release-tree validation, wheel/sdist construction, Twine checks, and clean-wheel installation run manually on a trusted machine via the documented release preflight. No automated validation executes repository code on maintainer hardware, and no secrets are exposed to any automated pipeline.

Ordinary contribution validation does not require current trusted benchmark evidence or a matching release source fingerprint. A source-changing contribution is expected to differ from the previous release evidence until a maintainer produces fresh trusted evidence. Final `--require-release-evidence` and `release_source_check.py` gates are therefore enforced manually by the maintainer in the release path.

Networked or credentialed measurement is separate. Real-paper discovery and LiteLLM smoke tests run only on trusted infrastructure controlled by the maintainer; untrusted pull-request code is never executed there.

Maintainer release validation keeps uploaded evidence deliberately narrow: release-promotable discovery/planning JSON plus the ReproBench manifest, summary, and sanitized result JSON. Temporary PDFs, cloned third-party repositories, experiment workspaces, provider prompts/responses, credentials, and raw logs remain transient state and are not redistributed as release evidence.

Before fresh evidence is promoted, the maintainer runs `scripts/release_source_check.py` on the exact release commit; that final integrity gate is expected to fail rather than silently accepting stale measurements.

If GitHub Actions workflows are restored in the future, they must remain fork-safe: no self-hosted runners for untrusted pull-request code, no repository secrets in public CI, and persisted credentials disabled at checkout. The release-tree checker and regression tests enforce these boundaries.

## Important residual risks

Docker alone is not sufficient isolation for intentionally hostile code, especially when the Docker daemon or image build is privileged. The experiment process now runs as an explicit non-root UID/GID, but that does not convert Docker into a rootless sandbox. Use an additional VM, ephemeral worker, rootless runtime, or hardened sandbox for adversarial repositories.

The runtime root filesystem is read-only and repository-relative writes are confined to bounded tmpfs overlays. This does not harden the earlier Docker image-build/dependency-install stage; intentionally hostile build hooks still require an isolated or rootless build backend outside the current runtime boundary.

Host-side downloads still depend on the operating system resolver and network stack. The downloader re-validates each redirect and rejects non-global resolved addresses, but users handling hostile inputs should run VeriRepro inside an isolated worker with egress controls.

Remote PDFs are byte-limited before parsing, but PDF parsing and text extraction still occur in the host Python process. A maliciously complex or highly compressed PDF may consume disproportionate CPU or memory even when its downloaded byte size is within the configured limit. Local PDFs also bypass the remote-download byte gate. Treat adversarial PDFs as untrusted parser input and use an isolated worker or external resource limits when that threat matters.

Repository acquisition is shallow and restricted to canonical HTTPS GitHub repositories with LFS smudge disabled, but VeriRepro does not currently enforce a hard byte quota on the Git object transfer or checked-out working tree. An unusually large repository can therefore consume host disk before later inspection/execution budgets apply. Use a disposable worker or filesystem quota for adversarial repositories.

Persistent experiment output remains a run-scoped host bind without a portable hard filesystem quota. VeriRepro bounds the amount it indexes and compares after execution; for less-trusted output writers, select `--output-backend ephemeral` so `/repro-output` is a host-budgeted tmpfs with no host bind. A disposable VM/filesystem quota is still appropriate when persistent artifacts are required from hostile code.

Figure similarity is a reproduction signal, not proof that a scientific conclusion is semantically identical. VeriRepro intentionally reports the comparison method and score rather than treating visual similarity as an oracle.

Docker image builds may execute third-party package-manager/build hooks and may need outbound package-index access to reconstruct dependencies. Those builds run before the non-root research-code runtime boundary and interact with the host Docker daemon. The double opt-in network policy applies to the research-code **runtime** container, not to dependency fetching during image construction. Build stdout/stderr is host-bounded and the Docker client is stopped on timeout, but daemon-side cancellation remains runtime-dependent. For hostile repositories, isolate the build itself in a disposable VM/worker or a genuinely rootless/hardened builder with egress controls.

The current clone policy intentionally supports only canonical HTTPS GitHub repositories. Supporting other Git hosts safely requires provider-specific source validation rather than silently relaxing the transport restrictions.

## Reporting vulnerabilities

Use the repository Security tab's private vulnerability-reporting flow for suspected sandbox escapes, SSRF bypasses, credential leaks, host-file read paths, or similar vulnerabilities. The public repository should keep GitHub private vulnerability reporting enabled so the configured Security advisory link remains available. Do not publish working exploit details in a public issue.
