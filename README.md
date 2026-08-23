# VeriRepro

**Evidence-grounded reproduction for computational papers.**

Give VeriRepro an arXiv paper, DOI, PDF URL, or local PDF. It builds an inspectable chain from paper claims to repository evidence, environment provenance, sandbox execution, scalar metrics, figures, and tables.

The governing rule is:

> **Models may propose. Deterministic code must verify.**

Unsupported model output is not promoted into scientific evidence, repository-authored expected values do not self-certify a paper, and a successful program exit does not automatically become a scientific `PASS`.

> Status: **0.8.0 public beta.** The public package, CLI, and Python namespace are `verirepro`. The legacy `reproagent` CLI/import remain compatibility aliases during the 0.x series.

The committed 0.8.0 release evidence covers a 15-paper repository-discovery corpus, bounded environment planning on three real repositories, and two end-to-end ReproBench seed cases. Those measurements certify only the tested gates and inputs; they are not a claim of arbitrary-paper zero-config reproduction.

## Quick start

Use a pinned paper from VeriRepro's fixed public smoke corpus so the first run follows a known, versioned input. The default quick start plans the reproduction without executing third-party experiment code or requiring a model endpoint:

```bash
git clone https://github.com/XiantingWu/VeriRepro.git
cd VeriRepro
python -m pip install .
verirepro doctor --json
verirepro plan 2103.00020v1
verirepro reproduce 2103.00020v1 --no-execute --no-llm
```

That first run is intentionally non-executing. Before allowing VeriRepro to execute third-party experiment code, run `verirepro doctor --strict`; add `--require-llm` if model-assisted analysis is required.

Python:

```python
import verirepro

report = verirepro.reproduce("2103.00020v1", execute=False, use_llm=False)
print(report.status)
```

`python -m verirepro` is also supported. Model-assisted paper analysis is optional and can be enabled after configuring an OpenAI-compatible/LiteLLM endpoint as described below.

A run preserves evidence instead of only printing a verdict:

```text
paper-intelligence.json
artifact-discovery.json
repository-plan.json
environment-plan.json
dataset-provenance.json
model-artifact-provenance.json
artifact-results.json
report.json
report.md
experiment.stdout.log
experiment.stderr.log
outputs/
```

## What VeriRepro verifies

```text
Paper
  ↓
page-grounded experimental claims
  ↓
ranked repository / dataset evidence
  ↓
repository-grounded execution plan
  ↓
Git + Python + dependency + CUDA provenance
  ↓
Docker sandbox
  ↓
experiment execution
  ↓
evidence-authorized metrics + Figure/Table/file checks
  ↓
PASS / FAIL / PARTIAL + evidence bundle
```

### Paper intelligence

- PDF page boundaries are preserved.
- Model-proposed factual claims require page/quote evidence.
- Quotes are verified against extracted page text.
- Numeric values must be supported by their cited quote.
- Unsupported claims become `UNVERIFIED`.
- Missing reproduction-critical details remain visible in an ambiguity audit.
- PDF URI annotations can recover repository/dataset links omitted by text extraction, while remaining distinct from scientific claim evidence.
- Repository occurrences, ranked candidates, annotation links, dataset URLs, and evidence anchors are host-bounded before they can expand downstream ranking/model work.

### Repository-grounded execution

When no explicit command is supplied, a model may choose only from real Python/Jupyter entrypoints found in the cloned repository. The proposed command must survive deterministic entrypoint, documentation-evidence, and syntax validation.

Generated plans reject shell chaining, redirects, command substitution, network utilities, package managers, invented entrypoints, and undocumented argument combinations. Safe abstention is preferred over a plausible-looking invented command.

### Environment provenance

Repository inspection records the resolved Git commit, Python constraints, dependency strategy, lockfiles, scientific-stack signals, CUDA/GPU hints, repository fingerprint, and environment fingerprint.

### Artifact verification

VeriRepro can compare declared Figure/Table/file outputs:

```yaml
version: 1
experiment:
  command: python reproduce.py
  network: false

metrics:
  - name: accuracy
    paper: 0.914
    tolerance: 0.01

artifacts:
  - name: Figure 3
    kind: figure
    reference: references/figure3.png
    reproduced: figure3.png
    threshold: 0.95

  - name: Table 2
    kind: table
    reference: references/table2.csv
    reproduced: table2.csv
    threshold: 1.0
    relative_tolerance: 0.01
```

Generated outputs are indexed with SHA-256. Figures use deterministic normalized visual comparison; CSV/TSV tables use structural and cell-level comparison with explicit numeric tolerances. Generic pixel similarity is a secondary signal, not proof of semantic plot equivalence.

## Scientific evidence authority

A third-party repository may describe **how to run itself**, but it may not silently define the scientific truth used to certify itself.

`verirepro.yaml` / `.verirepro.yaml` can provide execution configuration. Legacy `reproagent.yaml` names remain supported during the compatibility window.

Repository-authored `metrics` and `artifacts` are ignored for scientific `PASS`/`FAIL` by default. If a human has reviewed that contract and intentionally wants it to become verdict evidence:

```bash
verirepro reproduce 2103.00020v1 --trust-repository-contract
```

This grants scientific-contract authority only. It does not grant network access, broader filesystem access, Docker capabilities, host commands, or credentials.

For automatically extracted scalar metrics, the current deterministic policy permits normalized accuracy/F1/AUC/precision/recall-style comparisons with a fixed absolute tolerance of `0.01`. Scale-dependent metrics such as BLEU, loss, or latency remain informational unless a reviewed contract defines their semantics.

Experiment code must emit an explicit marker for scalar verdict evidence:

```python
print("VERIREPRO_METRIC accuracy=0.908")
```

The legacy `REPROAGENT_METRIC` prefix remains accepted. Arbitrary training-log strings such as `accuracy:` or `loss:` are not treated as final scientific results.

## Verdict semantics

- **PASS** — execution completed and every available evidence-authorized scientific comparison passed.
- **FAIL** — a required dataset/environment/execution stage failed, host-side safety verification failed, or at least one evidence-authorized metric/artifact comparison failed.
- **PARTIAL** — no hard pipeline failure occurred, but the available evidence is insufficient to establish scientific `PASS`/`FAIL` (for example, execution succeeded without an independently authorized metric/artifact comparison).

`PARTIAL` is intentional. VeriRepro does not convert “the script exited 0” into “the paper was reproduced,” and it does not downgrade hard execution/infrastructure failures to `PARTIAL`.

## ReproBench

VeriRepro exposes an agent-agnostic ReproBench boundary without requiring a separate ReproBench source checkout.

Run one task:

```bash
verirepro-reprobench task.json --output result.json
```

Aggregate fixed result evidence:

```bash
verirepro-reprobench-summary results/*.json --output summary.json
```

The adapter records:

- success / partial / failure;
- environment-build and experiment-execution status;
- grounded metric and artifact comparison counts/rates;
- expected-artifact coverage;
- failure taxonomy;
- wall-clock runtime;
- repository/environment provenance;
- operator intervention count;
- provider-reported model token/runtime/cost telemetry when available.

Task JSON is untrusted: local/file/insecure-HTTP paper sources are rejected, expected-artifact paths are confined, files are size-bounded, symlinks and non-standard `NaN`/`Infinity` JSON are rejected, and unknown fields are recorded but never executed.

Result aggregation enforces outcome/taxonomy consistency: `success` cannot carry failures; `partial` is reserved for `insufficient_evidence_or_execution`; hard taxonomy entries require `failure`. The final release-evidence checker independently revalidates the same contract and recomputes outcome counts/rates from the committed results.

The canonical 0.8 seed suite uses CPU-capable public repositories pinned to immutable commits. Repository/ref/command overrides remain visible as interventions. The release gate can therefore require successful Docker environment construction and experiment execution while still expecting a scientifically honest `PARTIAL` when there is no independently authorized metric/artifact contract.

See `docs/REPROBENCH.md` for the task/result/summary schemas, seed policy, evidence hashes, exact-head provenance, and release gate.

## Real-paper evidence

The fixed discovery corpus in `benchmarks/real-paper-smoke.json` contains 15 public papers across vision/NLP and computational-science domains. Every arXiv input is pinned to an explicit revision and the result is bound to the exact corpus bytes by SHA-256.

Deterministic discovery/evidence gate:

```bash
python scripts/run_real_paper_smoke.py \
  --require-top1 \
  --require-evidence
```

Bounded real-repository environment planning:

```bash
python scripts/run_real_paper_smoke.py \
  --require-top1 \
  --require-evidence \
  --inspect-repositories \
  --max-cases 3
```

These measurements test repository discovery/evidence and environment planning. They do **not** claim that all 15 papers were fully reproduced. End-to-end execution rates belong to ReproBench.

See `docs/REAL_PAPER_SMOKE.md`.

## Dataset providers

Direct HTTPS, Hugging Face, and Zenodo declarations are supported.

```yaml
datasets:
  - name: validation
    provider: huggingface
    repo_id: my-org/my-dataset
    revision: 4f6d2c1
    path: data/validation.parquet
    max_bytes: 1073741824
```

Host-side downloads enforce HTTPS-by-default, public-IP/DNS checks, redirect re-validation, host-owned byte ceilings, atomic partial files, symlink refusal, and optional SHA-256 verification. Hugging Face credentials are scoped to the original Hugging Face host and stripped on cross-host redirects. Credentials are never forwarded into experiment containers.

See `docs/DATASETS.md`.

## LiteLLM / OpenAI-compatible models

VeriRepro uses an OpenAI-compatible endpoint and does not require a provider SDK.

```bash
export VERIREPRO_LITELLM_BASE_URL="https://your-litellm.example.com"
export VERIREPRO_LITELLM_API_KEY="..."
export VERIREPRO_LITELLM_MODEL="research-model"
```

`LITELLM_*` variables also work, and legacy `REPROAGENT_LITELLM_*` aliases remain during the 0.x transition. There is intentionally no `--api-key` CLI argument.

Benchmark telemetry retains only a bounded whitelist such as model names, latency, token counts, and provider-reported cost. Endpoint URLs, credentials, prompts, and response content are excluded. Cost is never guessed from model names or price tables; absent provider cost remains `null`.

Disable model reasoning while retaining deterministic stages:

```bash
verirepro reproduce 2103.00020v1 --no-llm
```

## Security model

VeriRepro handles untrusted paper URLs/text, model output, Git repositories, manifests, dataset URLs, artifact paths, and experiment output.

The experiment runtime uses Docker with a read-only root filesystem, an explicit non-root UID:GID, bounded writable tmpfs overlays, network disabled by default, Linux capabilities dropped, `no-new-privileges`, init, PID limits, CPU/memory limits, and no LiteLLM credentials in the container. Runtime networking requires both a repository request and explicit host `--allow-network` authorization. Model artifacts are materialized on the host with checksum/provenance controls and mounted read-only.

Host-side paper/dataset downloads have address, redirect, path, and byte/count controls. Repository acquisition is separately restricted to canonical HTTPS GitHub URLs, conservative refs, shallow/no-tag operations, and disabled Git `file`/`ext` and LFS smudge; it does **not** currently impose a hard byte quota on Git transfer/checkout. See `docs/TRUST_MODEL.md` and `SECURITY.md` for the exact controls and residual resource risks.

## Release engineering

Maintainer release candidates are validated from the repository root with the same public package surface that users install:

```bash
python -m pip install -e '.[dev]'
pytest -q
verirepro --version
verirepro doctor --json
python scripts/release_check.py
python scripts/launch_surface_check.py
```

The public CI design runs untrusted fork PRs only on GitHub-hosted ephemeral runners with read-only permissions, no repository secrets, and non-persistent checkout credentials. Networked/credentialed smoke remains maintainer-dispatched on trusted infrastructure. Publication uses PyPI Trusted Publishing/OIDC rather than a long-lived PyPI token.

Final publication additionally runs:

```bash
python scripts/launch_surface_check.py
python scripts/release_check.py --require-release-evidence
python scripts/release_source_check.py
```

For 0.8, that gate requires **version-matched** 15-paper discovery evidence and bounded 3-repository environment-planning evidence from the frozen 0.8 source, plus version-matched ReproBench evidence with suite/task/result/summary hashes and GitHub Actions provenance. Historical 0.7 evidence remains immutable provenance for 0.7 but cannot certify the changed 0.8 runtime/package source merely because benchmark inputs are unchanged. The release source fingerprint also covers the front-half measurement/promotion policy and public-launch policy, and the final checker independently revalidates ReproBench outcome/failure-taxonomy semantics and recomputes aggregate outcome rates from committed result evidence.

## Current limitations

- General figure comparison is visual/pixel-based, not semantic plot understanding.
- Automatic PDF Figure/Table crop-to-output matching is still incomplete.
- Environment reconstruction cannot make an underspecified or unavailable upstream dependency reproducible.
- NVIDIA/CUDA hardware execution remains unverified until a matching NVIDIA-capable trusted runner exists; the GPU authorization contract itself is tested.
- Repository checkout does not currently have a hard transfer/working-tree byte quota. Persistent experiment outputs likewise are not a hard filesystem quota; less-trusted runs can instead use `--output-backend ephemeral` for a host-budgeted disposable tmpfs.
- Dependency/image builds still interact with the Docker daemon before the non-root research-runtime boundary; hostile builds require a disposable VM, rootless builder, or equivalent infrastructure.
- A small seed ReproBench suite is evidence of the tested cases only; it is not a claim of arbitrary-paper zero-config reproduction.

## Project documents

- `docs/ARCHITECTURE.md`
- `docs/TRUST_MODEL.md`
- `docs/REPROBENCH.md`
- `docs/REAL_PAPER_SMOKE.md`
- `docs/DATASETS.md`
- `docs/MODEL_ARTIFACTS.md`
- `docs/OUTPUTS.md`
- `docs/GETTING_STARTED.md`
- `docs/LITELLM.md`
- `docs/SCHEMAS.md`
- `docs/PUBLISHING.md`
- `ROADMAP.md`
- `CONTRIBUTING.md`
- `SECURITY.md`

## License

Apache-2.0. See `LICENSE`.

For academic use, see `CITATION.cff`.
