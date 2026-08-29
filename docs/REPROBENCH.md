# ReproBench integration

VeriRepro integrates with ReproBench through a **versioned JSON/process boundary**. It does not require a separate ReproBench source checkout or a hidden sibling import.

This keeps VeriRepro independently installable while allowing benchmark harnesses to evaluate it through stable task/result contracts.

## Commands

Run one task:

```bash
verirepro-reprobench task.json --output result.json
```

Useful policy switches remain explicit:

```bash
verirepro-reprobench task.json \
  --no-llm \
  --no-execute \
  --output result.json
```

Aggregate a fixed set of result files deterministically:

```bash
verirepro-reprobench-summary results/*.json --output summary.json
```

`--repo`, `--ref`, `--command`, `--allow-network`, and `--trust-repository-contract` are supported for controlled experiments, but applicable overrides are recorded as operator interventions. They are never silently counted as zero-intervention autonomous performance.

## Task contract v1

Example:

```json
{
  "schema_version": 1,
  "task_id": "demo-001",
  "domain": "machine-learning",
  "paper": "arXiv:2401.00001",
  "expected_artifacts": ["metrics.json"]
}
```

Core fields:

- `task_id`: non-empty stable task identifier;
- `domain`: non-empty benchmark domain label;
- `paper`: arXiv/DOI identifier or credential-free HTTPS URL without query/fragment data;
- `expected_artifacts`: relative output file names/paths expected from the experiment.

### Trust boundary

A benchmark task is treated as **untrusted data**.

Therefore:

- task files are limited to 1 MiB;
- symlink task files are rejected;
- task-controlled local paper paths and `file://` URLs are rejected;
- insecure HTTP, URL credentials, query strings, and fragments are rejected;
- expected artifact paths must be relative files and may not contain `..`, absolute paths, Windows drive prefixes, or directory-only paths;
- at most 128 expected artifacts are accepted;
- unknown task fields are bounded and recorded in `task.extra_fields` but are **not interpreted or executed**;
- task JSON must be standards-compliant: `NaN` and `Infinity` are rejected.

Direct interactive `verirepro reproduce` may use a local PDF when the user explicitly supplies it. ReproBench receives narrower authority because benchmark definitions can originate outside the host trust boundary.

## Result contract v1

The adapter emits machine-readable JSON:

```json
{
  "schema_version": 1,
  "benchmark": "reprobench",
  "task": {
    "schema_version": 1,
    "task_id": "demo-001",
    "domain": "machine-learning",
    "paper": "arXiv:2401.00001",
    "expected_artifacts": ["metrics.json"],
    "extra_fields": []
  },
  "agent": {
    "name": "VeriRepro",
    "version": "0.8.0",
    "report_schema_version": 1
  },
  "outcome": "partial",
  "wall_clock_seconds": 12.34,
  "execution_requested": true,
  "operator_interventions": [],
  "intervention_count": 0,
  "measurements": {},
  "failure_taxonomy": [],
  "stages": []
}
```

The exact VeriRepro version is populated at runtime.

### Measurements

The adapter records, when available:

- raw VeriRepro `PASS` / `PARTIAL` / `FAIL` status;
- selected canonical repository URL;
- environment-plan availability;
- repository commit, environment fingerprint, reproducibility grade, and dependency strategy;
- Docker environment-build stage status;
- experiment execution stage status and success;
- grounded metric comparison count/pass rate;
- Figure/Table/file comparison count/pass rate;
- output artifact count;
- expected artifacts found/missing/rate;
- total adapter wall-clock time;
- operator intervention count;
- provider-reported model request/token/runtime/cost telemetry when LiteLLM is actually used.

The adapter deliberately does **not** copy free-form VeriRepro stage details or workspace/report paths into benchmark results. Stage evidence is reduced to bounded machine-readable status; host-specific diagnostics stay in the local VeriRepro report.

### Model usage and cost

A ReproBench task enters an opt-in context-local telemetry capture around the normal VeriRepro reproduction pipeline. Only a fixed public whitelist is retained: request/response model names, request count, prompt/completion/total/cached/reasoning tokens, model-call duration, provider-reported USD cost, and a bounded error type.

Endpoint/base URL, API keys, authorization headers, prompts, model response content, and future unknown client fields are dropped before capture.

Cost is **never estimated** from model names or token price tables. If the provider does not report cost, `model_cost_usd` remains `null`. Missing token fields also remain unknown rather than becoming invented zeros.

## Outcome semantics

`success` means VeriRepro returned `PASS`, every ReproBench `expected_artifact` was found, and no deterministic hard-failure category was recorded.

`partial` means VeriRepro returned `PARTIAL` without a benchmark-required artifact missing and without a deterministic hard failure. It is reserved for `insufficient_evidence_or_execution`: for example, a process may execute successfully but no independently authorized scientific comparison exists.

`failure` means VeriRepro returned `FAIL`, a benchmark-required artifact was missing, or deterministic stage/result evidence records a hard failure such as dataset materialization, environment build, experiment execution, output indexing, artifact verification, or a scientific/artifact mismatch.

The contract is enforced in both directions:

- `success` must have an empty `failure_taxonomy`;
- `partial` must declare exactly `insufficient_evidence_or_execution`;
- `failure` must declare at least one hard failure category and may not use the partial-only category.

The final release checker independently revalidates these semantics from committed result JSON and recomputes success/partial/failure counts and rates.

## Failure taxonomy

The result may include:

- `source_resolution_failure`
- `repository_discovery_failure`
- `repository_inspection_failure`
- `dataset_materialization_failure`
- `environment_build_failure`
- `experiment_execution_failure`
- `output_indexing_failure`
- `artifact_verification_failure`
- `grounded_metric_mismatch`
- `artifact_comparison_mismatch`
- `expected_artifact_missing`
- `insufficient_evidence_or_execution`
- `unclassified_verirepro_failure`

`insufficient_evidence_or_execution` is the only soft taxonomy entry and is valid only with `partial`.

`unclassified_verirepro_failure` is a defensive observability fallback: if a future failed stage has not yet received a dedicated ReproBench category, the failure remains visible instead of disappearing from benchmark statistics.

The taxonomy is derived from deterministic VeriRepro stage/result data rather than free-form model text.

## Summary contract v1

`verirepro-reprobench-summary` reads one or more result-v1 JSON files and produces deterministic summary-v1 JSON. It never runs an agent or experiment.

The aggregator validates every input, rejects symlinks, caps each result at 5 MiB, rejects non-finite JSON numbers and duplicate `task_id` values, and records each input by **basename + SHA-256 + task ID** rather than absolute host path. It also validates intervention counts, stage status shape, expected-artifact partitions, comparison counts, model-usage/cost values, and the outcome/failure-taxonomy contract before aggregation.

It computes:

- success / partial / failure rates;
- zero-intervention rate and total interventions;
- total / mean / median wall-clock time;
- environment-build attempted/pass rate;
- experiment-execution attempted/pass rate;
- grounded metric comparison totals/pass rate;
- Figure/Table/file comparison totals/pass rate;
- expected artifact found rate;
- provider-reported model cost totals and token/runtime totals, with explicit counts of cases that actually reported them;
- failure-taxonomy counts;
- per-domain outcome/success rates;
- agent/version counts.

Comparison and model-usage rates are calculated only from evidence that exists. Missing metric/artifact comparisons, tokens, or provider cost remain `null`, not invented success or zero-cost claims.

## 0.8 real seed end-to-end gate

`benchmarks/reprobench-seed-suite.json` is a deliberately small, repository-owned **execution policy**, not an untrusted task file and not a claim about broad paper reproducibility. Task JSON remains untrusted input; the suite records the host decisions required to evaluate it.

Run the canonical seed suite with:

```bash
python scripts/run_reprobench_seed.py \
  --output .verirepro/benchmarks/reprobench-seed
```

The 0.8 seed is intentionally bounded to CPU-capable public repositories pinned to immutable 40-character Git commit SHAs. Repository, ref, and command overrides remain explicit operator interventions. Runtime networking remains disabled, and `trust_repository_contract=false` for both canonical cases.

The gate asks a narrower question than “was the whole paper scientifically reproduced?” It requires that VeriRepro can resolve the paper, inspect the pinned repository, construct the environment, run the selected reproduction command through the normal Docker boundary, and report the result without inventing scientific evidence.

The two canonical cases deliberately exercise both honest outcomes:

- `governed-individuation-mechanism-v1` executes successfully but has no independently authorized scientific metric/artifact comparison, so its expected ReproBench outcome remains `partial`;
- `cohomology-wall-smoke-v1` receives a **benchmark-owned, host-authorized** table contract whose reference is stored under `benchmarks/reprobench-reference/`. The third-party repository still cannot authorize its own scientific truth. Its reproduction generates `verification_table.csv`, and VeriRepro compares only the explicitly selected rank/defect columns against the SHA-256-bound Section 7 reference. The canonical release expects this case to be `success`.

Thus both canonical **release gates** can pass while the aggregate scientific outcomes remain one `success` plus one intentional `partial`. This is deliberate: **program exit success is not promoted into scientific PASS without independently authorized metric/artifact evidence.**

For 0.8, final release evidence must contain at least one grounded scientific `success`. The release checker verifies the benchmark-owned reference hashes and refuses a scientific success that lacks that independent reference binding.

The seed suite must remain bounded and versioned. Future growth should add scientifically diverse cases without weakening pinning, intervention accounting, trust boundaries, or verdict semantics.

## Release evidence bundle

For 0.8, the committed release evidence is:

```text
benchmarks/real-paper-smoke-results-0.8.0.json
benchmarks/environment-planning-results-0.8.0.json
benchmarks/reprobench-results-0.8.0/
  manifest.json
  summary.json
  results/
    <task-id>.json
```

Trusted validation may use larger transient workspaces, but release evidence is intentionally narrow. It excludes paper PDFs, cloned third-party repositories, Docker contexts, experiment workspaces, stdout/stderr logs, credentials, prompts, and model-response content.

The ReproBench manifest binds evidence to:

- the exact VeriRepro release version;
- the exact seed-suite bytes by SHA-256;
- each task JSON by SHA-256;
- each result JSON by SHA-256;
- the aggregate summary by SHA-256;
- the deterministic release-source fingerprint;
- the exact tested source head SHA;
- the trusted workflow/run provenance;
- each case's declared release gate and whether it passed.

`python scripts/release_check.py --require-release-evidence` independently requires version-matched discovery, planning, ReproBench, and certification-environment evidence; recomputes committed hashes; revalidates every result's outcome/failure-taxonomy relationship; and recomputes aggregate outcome rates.

`python scripts/release_source_check.py` separately recomputes the deterministic release-source fingerprint and refuses publication if release-relevant source changed after trusted evidence was produced.

The fingerprint covers runtime/package source plus front-half measurement policy, evidence-promotion policy, ReproBench seed execution, final release/source checks, package metadata, public launch policy, and public CI/publish policy. Changing any release-relevant bytes after measurement invalidates the evidence.

The final release check also refuses result evidence that exposes host paths or secret-bearing fields such as API keys, authorization headers, endpoint/base URLs, prompts, responses, or workspace paths.

## Independence rule

The integration must remain valid without hidden local source dependencies. Do not add relative imports from unpublished sibling projects. If the ReproBench contract evolves, support it through an explicit versioned JSON/process adapter or a published dependency.
