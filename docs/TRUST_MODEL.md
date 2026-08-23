# Trust model

VeriRepro crosses several explicit trust boundaries. The system is designed so that data or code from one untrusted boundary cannot silently grant authority in another.

The central rule is:

> Models and third-party repositories may propose. Deterministic host policy decides what is evidence, what may execute, and what authority is granted.

## Paper source and paper text

A remote PDF URL is host-side network input, and extracted PDF text is untrusted natural-language data.

For remote paper materialization, VeriRepro applies:

- HTTPS by default;
- rejection of URL-embedded credentials;
- rejection of literal or DNS-resolved non-global destinations;
- manual redirect handling with validation of every redirect target;
- a 200 MiB default PDF limit, checked before and during streaming;
- an optional user-controlled `VERIREPRO_MAX_PDF_BYTES` host limit;
- temporary `.part` files followed by atomic replacement.

DOI metadata may be resolved through Crossref, but an exposed PDF URL still passes the same download policy before content is materialized.

After materialization, paper text is treated as **data**, not as instructions.

- page boundaries are preserved for evidence verification;
- model-proposed concrete claims require page/quote support;
- unsupported claims remain `unverified` and cannot become scientific PASS/FAIL evidence;
- whole-paper metric regex matches are not accepted as verdict evidence merely because a number appears near a metric name;
- bounded HTTP(S) PDF URI annotations may be used as deterministic repository/dataset discovery evidence when normal text extraction omits a hyperlink;
- annotation links remain separate from page/quote evidence;
- repository occurrences, ranked candidates, context occurrences, dataset URLs, annotation links, URL lengths, and per-repository evidence anchors are host-bounded before they can expand ranking or downstream model context.

## LLM output

LLM output is a proposal, not scientific ground truth and not an execution capability.

- repository selection is constrained to repositories found deterministically from paper evidence;
- a model-proposed command is usable only when its entrypoint exists in the cloned repository;
- supporting repository evidence must verify against allowed repository text;
- the complete normalized command must be documented and pass a narrow Python/Jupyter command validator;
- shell chaining, redirects, command substitution, control/newline separators, network utilities, package managers, invented entrypoints, undocumented flags, and ungrounded commands are rejected;
- missing reproduction-critical fields remain visible instead of being filled with model guesses.

LiteLLM may return usage telemetry. VeriRepro can record bounded request/response model identifiers, request count, latency, token counts, and provider-reported cost for benchmarking. That telemetry does not grant scientific authority and excludes API keys, private endpoint configuration, prompts, and response content from release evidence.

## Third-party repository acquisition and host inspection

Research repositories are untrusted before any experiment starts. VeriRepro currently limits host-side cloning to canonical HTTPS GitHub repository URLs of the form `https://github.com/<owner>/<repo>`.

- SSH, `file://`, Git `ext::`, embedded credentials, query strings, and unexpected GitHub path shapes are rejected;
- user-provided refs are conservatively validated before use;
- Git is invoked with `protocol.file.allow=never` and `protocol.ext.allow=never`;
- Git LFS smudge/process materialization is disabled during untrusted clone/checkout;
- clone/fetch use shallow, no-tag operations;
- host-side dependency/manifest/source inspection reads only real files whose resolved paths remain inside the cloned repository root;
- symlinked dependency files, manifests, source files, notebooks, and documentation inputs are ignored rather than followed into the host filesystem;
- repository manifests must be regular non-symlink files and are limited to 1 MiB before YAML parsing;
- text sent from repository documentation to planning models is bounded and uses the same symlink/root-confinement checks.

The GitHub-only restriction is a trust-boundary decision, not a statement that other Git hosts are inherently unsafe. Additional providers require provider-specific source validation rather than a generic transport relaxation.

Repository checkout is shallow, but VeriRepro does **not** currently impose a hard byte quota on Git object transfer or the checked-out working tree. An unusually large or adversarial repository can therefore consume host disk before later inspection/execution budgets apply. Use a disposable worker or filesystem quota when that threat matters.

## Scientific evidence authority

A repository may describe how it should be executed, but it is not automatically trusted to define the expected scientific result used to certify itself.

Repository manifest fields have different authority:

- `experiment.command`, dataset declarations, model-artifact declarations, and `experiment.network` are **configuration requests** subject to host validation;
- `metrics[].paper` and artifact reference declarations are **scientific expectations** and are withheld from PASS/FAIL by default because they come from the same repository being evaluated;
- page/quote-verified paper-intelligence metrics may become candidates for automatic verdicts only under VeriRepro's deterministic metric policy;
- repository-declared scientific expectations enter the verdict only after explicit host authorization through `--trust-repository-contract`, `VERIREPRO_TRUST_REPOSITORY_CONTRACT=1`, or the equivalent trusted Python API parameter.

`--trust-repository-contract` grants only scientific-contract authority. It does **not** grant network access, host filesystem access, Docker capabilities, host command execution, or credentials.

For model-extracted scalar metrics:

- the model does not choose PASS/FAIL tolerance;
- only normalized accuracy/F1/AUC/precision/recall-style metrics are currently eligible for automatic comparison;
- the metric name must be supported by grounded paper evidence;
- eligible automatic comparisons use VeriRepro's fixed absolute tolerance of `0.01`;
- scale-dependent or unsupported metrics such as BLEU, loss, or latency remain informational unless a reviewed contract supplies deterministic comparison semantics;
- conflicting independently grounded values for the same canonical metric are treated as ambiguous and excluded.

Experiment output has a symmetric evidence boundary. Only explicit markers can enter an automatic scalar comparison:

```text
VERIREPRO_METRIC accuracy=0.914
```

The legacy `REPROAGENT_METRIC` marker remains compatible. Arbitrary training-log strings such as `accuracy:`, `F1:`, or `loss:` are not automatic verdict evidence.

If execution succeeds but no independently authorized scientific comparison exists, the run remains `PARTIAL` rather than being promoted to `PASS`.

## Host-side datasets and model artifacts

Dataset and checkpoint declarations are untrusted repository content, but materialization happens on the host before read-only mounts are created for the experiment container.

Host-side downloads apply:

- HTTPS by default;
- no URL-embedded credentials;
- literal and DNS-resolved non-global address rejection;
- redirect re-validation;
- host-owned per-object, cumulative-byte, and count ceilings;
- repository-requested limits may lower but not raise host ceilings;
- output/temp path confinement and symlink refusal;
- bounded destination filenames and duplicate-target rejection;
- atomic partial files;
- optional or required SHA-256 verification according to artifact class;
- authorization stripping on cross-host redirects where credentials are used.

Cross-run dataset cache reuse is host-owned and checksum-bound. Reusable entries require a declared SHA-256, are rehashed before materialization, use path/no-follow checks, and serialize cooperating writers under bounded advisory locking. Cache provenance is sanitized and does not retain credentials, URL query strings, or host cache paths.

Model/checkpoint artifacts require SHA-256 before they can be materialized through the hardened host download path. Their provenance is sanitized and they are mounted read-only at `/models`; model-hub credentials are not forwarded into experiment containers.

For high-risk inputs, application-layer checks should be combined with infrastructure egress and filesystem controls.

## Build boundary versus runtime boundary

Dependency/image construction and research-code execution are separate trust boundaries.

Docker image construction may execute third-party package-manager or build hooks and may need outbound access to operating-system and Python package indexes. Build stdout/stderr is host-bounded, and timeout stops the attached client, but the Docker daemon and image build are **not** made rootless by VeriRepro's runtime controls.

For intentionally hostile repositories, isolate the build itself in a disposable VM, rootless builder, hardened sandbox, or equivalent worker with egress controls.

## Third-party experiment runtime

The final research-code container runs with a stronger boundary than the build stage:

- explicit non-root UID:GID;
- Docker read-only root filesystem;
- repository source sealed into the image and copied into a bounded writable `/workspace` tmpfs at runtime;
- separate bounded `/tmp` tmpfs;
- `/datasets` and `/models` mounted read-only;
- Linux capabilities dropped;
- `no-new-privileges` enabled;
- init process, PID limit, CPU limit, and memory limit;
- experiment networking disabled unless both the repository requests it and the user independently authorizes `--allow-network`;
- GPU devices unavailable unless both the repository requests them and the user independently authorizes `--allow-gpu`;
- LiteLLM credentials excluded from the experiment container;
- unique container names and bounded timeout cleanup.

`gpu_likely` or other environment detection is diagnostic only and cannot grant GPU device access.

Docker is an isolation layer, not a formal sandbox proof. Intentionally adversarial code should still run inside additional disposable infrastructure.

## Generated outputs and artifact paths

Reference artifacts are confined to the cloned repository root. Reproduced artifacts are confined to the run output root. Path traversal outside either root is rejected.

Output indexing refuses symlinks and applies host-owned entry-count, file-count, per-file-byte, and cumulative-read budgets before hashing files. Figure/Table/file verification independently applies comparison-byte, table-byte/cell, and image-pixel budgets. Safety-budget violations become explicit failed stages rather than uncaught host exceptions.

Persistent `/repro-output` uses a run-scoped host bind and does not provide a portable hard filesystem quota. For less-trusted output writers, `--output-backend ephemeral` places `/repro-output` on a host-budgeted non-root tmpfs; file output is discarded when the container exits and over-budget writes fail inside the disposable volume.

Output files do not become scientific evidence automatically. Repository-declared reference/reproduced pairs affect PASS/FAIL only after explicit scientific-contract authorization.

## ReproBench task and result boundary

ReproBench task JSON is untrusted benchmark data and receives less authority than an interactive user invocation.

- task files are regular-file and size bounded;
- task paths may not rely on symlinked files or symlinked parent components in the canonical seed harness;
- task-controlled paper sources are limited to arXiv/DOI identifiers or credential-free HTTPS URLs without query/fragment data;
- local paths, `file://`, insecure HTTP, path traversal, Windows drive paths, and directory-only expected-artifact paths are rejected;
- unknown fields are bounded and recorded but never interpreted as executable policy.

ReproBench results remove free-form stage details and host workspace/report paths. They retain the bounded measurements needed for benchmarking, explicit operator interventions, deterministic failure taxonomy, and a fixed non-secret model-usage telemetry whitelist.

Outcome/taxonomy consistency is machine-enforced: `success` has no failure taxonomy; `partial` is reserved for `insufficient_evidence_or_execution`; hard taxonomy entries require `failure`. The deterministic aggregator enforces this contract, and the final release checker independently revalidates it and recomputes aggregate outcome rates from committed result JSON.

The 0.8 seed suite pins public repositories to immutable commits, keeps runtime networking disabled, records repository/ref/command overrides as interventions, and does not promote successful process execution into scientific PASS without independently authorized evidence.

## Release evidence

The fixed 15-paper front-half corpus records source-evaluable cases, deterministic repository found/top-1/evidence-anchor rates, per-domain counts, source/pipeline status, bounded environment-planning status, and safe entrypoint hint versus abstention.

Repository planning distinguishes `planned`, `unsupported`, `infrastructure_error`, `planning_error`, and `not_attempted`. A safe abstention is not rewritten as a successful command and infrastructure failure is not rewritten as scientific failure.

For each release, front-half measurements and ReproBench evidence must be produced from the release-relevant source bytes for that version. Stable benchmark inputs do not prove stable algorithm behavior after source changes.

The release-source fingerprint covers package/runtime Python, `pyproject.toml`, measurement/promotion policy, the ReproBench seed runner, public launch policy, and the public CI/publish workflows. Changing release-relevant bytes after evidence production invalidates the evidence and requires a fresh trusted measurement run. Documentation and promoted evidence files are intentionally outside that source fingerprint.

## Secrets

LiteLLM credentials remain in host-side orchestration and are not injected into third-party experiment containers, reports, command-line arguments, or release evidence.

VeriRepro supports `VERIREPRO_LITELLM_*`, standard `LITELLM_*`, and legacy `REPROAGENT_LITELLM_*` variables. A separately configured LiteLLM base URL does not accidentally inherit an unrelated `OPENAI_API_KEY`.

For gated/private Hugging Face files, `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` is used only for the initial Hugging Face request host. If the request redirects to another host, sensitive authorization headers are stripped before following the redirect.

## Public CI and maintainer integrations

Ordinary `push` and `pull_request` CI runs on GitHub-hosted ephemeral workers with read-only repository permissions, no repository secrets, and checkout credentials disabled. External fork pull requests therefore receive package/test/build validation without executing their code on maintainer hardware.

Ordinary fork PR CI does not require fresh trusted benchmark evidence or a matching release-source fingerprint, because legitimate source-changing contributions necessarily differ from the previous release evidence. Final version-matched evidence and `release_source_check.py` remain maintainer release responsibilities and are enforced again by the publish workflow.

Networked or credentialed real-paper/LiteLLM integration smoke remains separate and maintainer-dispatched. Self-hosted or credentialed runners must never execute arbitrary external fork pull-request code.

Trusted release evidence is deliberately narrow: promoted discovery/planning JSON and the ReproBench manifest/summary/result JSON. Paper PDFs, cloned repositories, Docker contexts, workspaces, prompts/responses, credentials, and raw logs remain transient state rather than public release evidence.

## What this trust model does not claim

VeriRepro does not claim that:

- Docker alone safely contains intentionally hostile build code;
- remote or local PDF parsing is immune to parser resource-exhaustion attacks;
- shallow Git clone provides a hard repository byte quota;
- visual figure similarity proves semantic scientific equivalence;
- environment reconstruction can recover unavailable or underspecified upstream dependencies;
- GPU support has been hardware-certified on NVIDIA merely because authorization logic is tested;
- a small benchmark seed establishes arbitrary-paper reproducibility.

For operational details and current residual risks, also read `SECURITY.md`, `docs/OUTPUTS.md`, `docs/DATASETS.md`, `docs/MODEL_ARTIFACTS.md`, and `docs/GPU.md`.
