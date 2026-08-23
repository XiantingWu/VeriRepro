# Real-paper discovery and planning corpus

`benchmarks/real-paper-smoke.json` is a bounded, networked corpus for the deterministic front half of VeriRepro. It measures specific discovery and planning capabilities instead of implying end-to-end scientific reproduction.

The corpus does **not** train models or claim that an experiment was reproduced. The default runner does not call an LLM. Repository inspection is optional and shallow; optional model-assisted planning is measured separately and never executes generated commands.

## Fixed 15-paper corpus

The current corpus contains 15 public arXiv papers across vision, NLP, computational science, scientific ML, and quantum-computing domains. Every source is pinned to an explicit arXiv revision so benchmark inputs cannot silently change when authors upload a new version.

- CLIP — `2103.00020v1` → `OpenAI/CLIP`
- LoRA — `2106.09685v2` → `microsoft/LoRA`
- ALBERT — `1909.11942v6` → `google-research/ALBERT`
- Diffusion Models Beat GANs — `2105.05233v4` → `openai/guided-diffusion`
- Improved DDPM — `2102.09672v1` → `openai/improved-diffusion`
- DETR — `2005.12872v3` → `facebookresearch/detr`
- Transformer-XL — `1901.02860v3` → `kimiyoung/transformer-xl`
- BERT — `1810.04805v2` → `google-research/bert`
- Swin Transformer — `2103.14030v2` → `microsoft/Swin-Transformer`
- MoBY — `2105.04553v2` → `SwinTransformer/Transformer-SSL`
- PySINDy — `2004.08424v1` → `dynamicslab/pysindy`
- JAX MD — `1912.04232v2` → `google/jax-md`
- AdaAF for PINNs — `2308.04073v1` → `LeapLabTHU/AdaAFforPINNs`
- Quantum HSGPQ — `2502.14467v1` → `cagalvisf/Quantum_HSGPQ`
- Tensor Network Decoding Beyond 2D — `2310.10722v2` → `ChriPiv/tndecoder3d`

A known official repository is not sufficient reason to make a case pass: the supplied pinned PDF must expose evidence that VeriRepro can discover. If a case reveals a general PDF/discovery defect, the defect should be fixed generically and converted into an offline regression test rather than paper-ID-specific runtime logic.

The **input corpus** is intentionally stable, but the **measured evidence is versioned**. An unchanged corpus SHA-256 proves only that the same papers were supplied. It does not prove that a changed discovery/planning implementation behaved the same. Every release that changes release-relevant discovery/planning source must rerun the corpus and promote new version-matched evidence.

## Input immutability and provenance

The runner rejects unversioned arXiv IDs in the release corpus. Before evaluation it hashes the exact corpus file bytes with SHA-256. Every machine result records:

- `corpus_sha256`;
- `corpus_revision_policy: explicit-arxiv-vN`;
- the exact per-case pinned source ID;
- the normal per-case discovery evidence and outcome.

Versioned release evidence is accepted only when its stored corpus SHA-256 equals the current committed corpus bytes **and** its release version matches the package release being certified.

The release-source fingerprint also covers `scripts/run_real_paper_smoke.py` and `scripts/record_release_evidence.py`. Changing measurement or promotion policy after a trusted run therefore invalidates the release evidence even when corpus bytes and version strings are unchanged.

## Deterministic discovery measurement

Run the corpus:

```bash
python scripts/run_real_paper_smoke.py
```

The release discovery gate is stricter:

```bash
python scripts/run_real_paper_smoke.py \
  --require-top1 \
  --require-evidence
```

Per case, the JSON records:

- whether the expected author repository was found;
- its rank;
- the top candidate and scored candidates;
- a page-level evidence anchor for the expected repository;
- whether that anchor came from extracted page text or a PDF URI annotation;
- bounded context for visible-text evidence;
- deterministic discovery runtime;
- domain and source/discovery status.

The evidence anchor is deterministic discovery provenance, not an LLM assertion. `metadata["pages"]` remains extracted page text for scientific page/quote grounding; PDF URI annotations are kept as a separate deterministic source and receive conservative ranking weight.

Host-owned limits bound repository occurrences, ranked candidates, context-phrase occurrences, dataset URLs, annotation links, annotation URL length, and per-repository evidence anchors before candidate data can expand ranking or downstream model context.

## Source failures versus algorithm failures

Networked benchmarks can fail before the discovery algorithm receives a usable paper. The result therefore keeps two views:

- compatibility totals such as `found_rate` and `top1_rate`, over all requested cases;
- algorithm rates such as `algorithm_found_rate`, `algorithm_top1_rate`, and `algorithm_evidence_anchor_rate`, over cases whose paper source was successfully materialized.

`discovery_status` distinguishes source/infrastructure failures from evaluable algorithm outcomes. Domain summaries use only source-evaluable cases for algorithm counts. This prevents an arXiv/network outage from being silently reported as a repository-ranking regression while still keeping the total run failure visible.

The 0.8 release gate is intentionally stricter than the reporting taxonomy: all 15 pinned sources must be evaluable and all 15 expected repositories must be found, ranked first, and evidence-anchored.

## Bounded environment-planning measurement

The same runner can shallow-clone expected repositories that were successfully discovered and measure deterministic repository/environment inspection:

```bash
python scripts/run_real_paper_smoke.py \
  --require-top1 \
  --require-evidence \
  --inspect-repositories \
  --require-environment-plan \
  --max-cases 3
```

The result records the pinned repository commit, inferred Python version/source, dependency strategy/files, reproducibility grade, GPU likelihood, deterministic entrypoint hint, runtime, warnings, and an explicit status taxonomy. `planned`, `unsupported`, `infrastructure_error`, `planning_error`, and `not_attempted` are not collapsed into one generic reproduction failure.

The bounded 0.8 release gate requires the first three repositories to produce 3/3 environment plans. A missing deterministic entrypoint is recorded as an explicit safe abstention rather than inventing a command.

The version-matched planning result is committed as:

```text
benchmarks/environment-planning-results-0.8.0.json
```

from the same trusted release measurement identity as the 0.8 discovery and ReproBench evidence.

## Optional LiteLLM planning measurement

`scripts/run_llm_planning_smoke.py` measures the model-assisted planning layer separately. It:

1. requires deterministic discovery to select the expected repository before spending a model request;
2. analyzes the supplied paper with evidence verification;
3. shallow-clones the repository;
4. asks the repository planner for a grounded safe command;
5. records `safe_command`, safe abstention, or an explicit error class;
6. records request/response model, request count, latency, prompt/completion/total/cached/reasoning tokens, and provider-reported cost when available;
7. **never executes the generated command**.

Model-assisted planning remains explicit and default-off so ordinary CI cannot silently consume model quota.

## 0.8 release evidence

The committed front-half evidence for 0.8 is:

```text
benchmarks/real-paper-smoke-results-0.8.0.json
benchmarks/environment-planning-results-0.8.0.json
```

The discovery evidence represents a 15/15 release gate for source evaluability, repository discovery, correct top-1 ranking, and evidence anchoring. The bounded environment-planning evidence represents 3/3 required plans.

These are front-half measurements only. Full environment-build, experiment-execution, scientific metric, Figure/Table/file, intervention, and failure-taxonomy measurements belong to the ReproBench evidence bundle.

`python scripts/release_check.py --require-release-evidence` requires these files to match the package release, committed corpus bytes, trusted measurement provenance, and the same release-source fingerprint used by the corresponding ReproBench evidence.
