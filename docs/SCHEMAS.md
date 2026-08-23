# Machine-readable schema policy

VeriRepro exposes several versioned machine-readable contracts. Downstream tooling should rely on explicit schema versions and documented compatibility rules rather than internal Python dataclasses.

## `verirepro.yaml` manifest

The preferred manifest filenames are `verirepro.yaml` and `.verirepro.yaml`. Legacy `reproagent.yaml` and `.reproagent.yaml` names remain supported during the 0.x compatibility window.

The top-level `version` field is conceptually required and defaults to `1` only for legacy compatibility. Current releases reject manifest versions other than `1` instead of guessing how to interpret them.

Schema v1 top-level keys include:

- `experiment`: command plus requested runtime capabilities such as network and GPU access;
- `datasets`: direct URL, Hugging Face, or Zenodo dataset declarations;
- `model_artifacts`: checksum-bound model/checkpoint declarations materialized on the host and mounted read-only;
- `metrics`: paper metric values and tolerances;
- `artifacts`: reference/reproduced Figure/Table/file comparisons.

Repository manifests are untrusted host input, not general-purpose YAML. VeriRepro applies a 1 MiB file ceiling, uses a SafeLoader-derived strict parser, rejects YAML aliases and duplicate mapping keys, requires capability requests such as `experiment.network` and `experiment.gpu` to be real booleans, and bounds the number of dataset, model-artifact, metric, and artifact declarations. Scientific numeric values and tolerances must be finite; NaN and infinity are rejected. These are host safety/correctness constraints rather than schema-extension points, so repository content cannot raise host-owned limits.

A manifest capability request is not an authority grant. Runtime networking requires independent user `--allow-network` authorization; GPU device access requires independent `--allow-gpu` authorization. Repository-authored `metrics` and `artifacts` likewise do not affect PASS/FAIL unless the host explicitly authorizes the reviewed repository scientific contract.

New optional fields may be added to schema v1 when they are backward compatible and do not silently broaden existing authority. Removing or changing the meaning, type, or authority of an existing field requires a new schema version.

## `report.json`

Every current report includes:

```json
{
  "schema_version": 1
}
```

Report schema v1 preserves the current meaning of:

- source and overall status;
- repository and detected stack;
- ordered pipeline stage results;
- paper/reproduced scalar metrics and comparisons;
- paper intelligence / repository plan / environment plan payloads;
- artifact discovery;
- dataset and model-artifact provenance when applicable;
- authorized artifact comparisons and output inventory;
- workspace and report paths in the local run report.

New keys may be added without incrementing the schema version when existing consumers can safely ignore them. Existing keys must not be silently repurposed. A breaking removal, type change, or semantic/authority change requires a new report schema version.

## ReproBench task JSON

VeriRepro 0.8 accepts ReproBench task schema v1 through the JSON/process adapter. A missing `schema_version` is interpreted as v1 only for compatibility with existing task files.

Core task fields are:

- `task_id`;
- `domain`;
- `paper`;
- `expected_artifacts`.

Benchmark task data is untrusted and has narrower authority than an interactive `verirepro reproduce` invocation. Local/file/insecure-HTTP paper sources, secret-bearing URLs, unsafe artifact paths, symlink task files, non-finite JSON numbers, and unbounded task data are rejected. Unknown fields are bounded and recorded by name but are not interpreted or executed.

## ReproBench result JSON

VeriRepro 0.8 emits result schema v1. The stable top-level meaning includes:

- benchmark/task identity;
- agent/version/report-schema identity;
- `success` / `partial` / `failure` outcome;
- execution-requested state;
- wall-clock duration;
- explicit operator interventions and count;
- deterministic measurements;
- failure taxonomy;
- sanitized stage name/status records.

Free-form stage details, workspace/report paths, API credentials, endpoint configuration, prompts, and model responses are intentionally excluded from benchmark results. Provider-reported model telemetry is retained only through the documented bounded whitelist.

Outcome and failure taxonomy are coupled: `success` cannot carry failure entries; `partial` is reserved for `insufficient_evidence_or_execution`; hard failure categories require `failure`. A breaking change to outcome semantics, required fields, field types, or authority rules requires a new result schema version.

## ReproBench summary JSON

`verirepro-reprobench-summary` emits summary schema v1 from validated result-v1 files. The summary records input basenames and SHA-256 digests rather than absolute host paths and computes aggregate outcome, intervention, runtime, environment-build, experiment-execution, grounded-metric, artifact, expected-artifact, model-usage, failure-taxonomy, domain, and agent/version statistics.

Summary inputs are treated as untrusted evidence: symlinks, oversized files, non-finite JSON, duplicate task IDs, malformed stage shapes, inconsistent intervention counts, inconsistent expected-artifact partitions, and outcome/taxonomy contradictions are rejected.

See `REPROBENCH.md` for the complete ReproBench task/result/summary contract and release-evidence semantics.

## Release evidence contracts

Release evidence is version-matched measurement output, not an unversioned cache of prior benchmark results. For 0.8 the committed bundle consists of:

```text
benchmarks/real-paper-smoke-results-0.8.0.json
benchmarks/environment-planning-results-0.8.0.json
benchmarks/reprobench-results-0.8.0/
```

The final release checker validates their release version, hashes, provenance, result semantics, and aggregate consistency. `release_source_check.py` independently verifies that the committed evidence still matches the deterministic fingerprint of release-relevant source and policy bytes.

Changing a schema interpretation or authority rule that is part of release-relevant code/policy requires fresh release evidence even when input benchmark files are unchanged.

## Verdict compatibility

The public VeriRepro verdict set is currently:

- `PASS`;
- `FAIL`;
- `PARTIAL`.

ReproBench adapter outcomes are separately:

- `success`;
- `partial`;
- `failure`.

A ReproBench `success` is not a synonym for process exit code zero: it requires the underlying VeriRepro result to satisfy scientific PASS semantics plus benchmark-required artifact coverage. Downstream consumers should treat unknown future verdicts, outcomes, or schema versions conservatively rather than mapping them to success.
