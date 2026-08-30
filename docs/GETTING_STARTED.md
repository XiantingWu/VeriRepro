# Getting started

This guide is the shortest safe path from a fresh checkout to a first VeriRepro run.

## 1. Install from the repository

```bash
git clone https://github.com/XiantingWu/VeriRepro.git
cd VeriRepro
python -m pip install .
```

Contributors who need the test and release toolchain can instead install the editable development environment:

```bash
python -m pip install -e '.[dev]'
```

The public CLI is `verirepro`. The legacy `reproagent` command remains a compatibility alias during the 0.x series.

## 2. Start with a bounded no-execution run

Use a pinned paper from the fixed release corpus so your first run has a known, versioned input. A normal diagnostic report is useful here but does not turn optional execution prerequisites into a barrier to trying the planner:

```bash
verirepro doctor --json
verirepro plan 2103.00020v1
verirepro reproduce 2103.00020v1 --no-execute --no-llm
```

This resolves the paper, discovers repository evidence, inspects the repository, and plans the environment without executing third-party experiment code or requiring a model endpoint.

## 3. Run strict preflight before executing experiments

For a normal CPU reproduction that will execute third-party experiment code, Git and a live Docker daemon are required. Model-assisted analysis is optional.

```bash
verirepro doctor --strict
```

The command exits with status `0` only when the required local prerequisites are ready. Use JSON in automation or issue reports when needed:

```bash
verirepro doctor --strict --json
```

The JSON reports only whether an optional model endpoint and model are configured; it never prints endpoint URLs or credential values.

If the workflow you intend to run requires model-assisted paper analysis, make that requirement explicit:

```bash
verirepro doctor --strict --require-llm
```

Without `--require-llm`, an absent model endpoint does not make the host unready because deterministic planning and `--no-llm` execution remain supported.

## 4. Inspect the evidence bundle

A reproduction workspace preserves machine-readable evidence rather than only printing a verdict. Depending on the run, it can include:

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

Treat `PASS`, `FAIL`, and `PARTIAL` as evidence states, not process-exit aliases. In particular, an experiment that exits successfully without independently authorized scientific evidence can remain `PARTIAL`.

## 5. Enable privileged capabilities deliberately

Experiment networking and GPU access use double authorization. A repository request alone is insufficient; the operator must also provide the corresponding CLI authorization.

```bash
verirepro reproduce <paper> --allow-network
verirepro reproduce <paper> --allow-gpu
```

Repository-declared expected metrics and reference artifacts also do not self-certify scientific correctness. Only use `--trust-repository-contract` after reviewing that contract.

## Troubleshooting handoff

When filing an environment issue, attach the output of:

```bash
verirepro doctor --json
```

Do not post API keys, private endpoint URLs, or unrelated runner logs. The doctor payload is designed to be secretless and machine-readable.

For the exact trust boundaries and residual risks, read `TRUST_MODEL.md` and the repository-level `SECURITY.md`.
