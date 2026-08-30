# VeriRepro

[![Python 3.11–3.13](https://img.shields.io/badge/Python-3.11--3.13-3776AB?logo=python&logoColor=white)](#quick-start)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Typing: PEP 561](https://img.shields.io/badge/typing-PEP%20561-informational)](#python-api)

**Evidence-grounded reproduction for computational papers.**

Give VeriRepro an arXiv paper, DOI, PDF URL, or local PDF. It builds an inspectable chain from paper claims to repository evidence, environment provenance, sandbox execution, scalar metrics, figures, tables, and a machine-readable reproduction report.

> **Models may propose. Deterministic code must verify.**

VeriRepro is designed for the gap between “the code ran” and “the scientific result was actually reproduced.” Unsupported model output is never promoted into scientific evidence, repository-authored expected values do not self-certify a paper, and a successful process exit does not automatically become a scientific `PASS`.

**Status:** VeriRepro is a public-beta Python package distributed through PyPI and released from the canonical [XiantingWu/VeriRepro](https://github.com/XiantingWu/VeriRepro) repository. `python -m pip install verirepro` installs the current published package. Version-specific certification and release authorities are recorded in [docs/EVIDENCE.md](docs/EVIDENCE.md) and GitHub Releases, not in this package description. The preferred package, CLI, and Python namespace are `verirepro`; the legacy `reproagent` CLI/import remain compatibility aliases during the 0.x series. The authoritative repository/package identity is defined in [docs/CANONICAL_IDENTITY.md](docs/CANONICAL_IDENTITY.md); similarly named copies are not release authorities by name alone.

## Why VeriRepro

- **Evidence before confidence.** Paper claims can carry page/quote support, and unverifiable claims remain visibly unverified.
- **Reproduction is not process success.** `PASS`, `FAIL`, and `PARTIAL` are evidence states, not aliases for exit code 0/1.
- **Repository code does not grade itself.** Third-party manifests may request execution configuration, but scientific expectations require independent evidence or explicit human authorization.
- **Execution authority is narrow.** Network, GPU, filesystem, model, dataset, and scientific-contract authority are separate controls.
- **Release claims are source-bound.** Real-paper and ReproBench evidence is tied to the release-relevant source identity that produced it.

## Quick start

Install the published package from PyPI, then start with a pinned paper from VeriRepro's fixed public smoke corpus. This path plans the reproduction without executing third-party experiment code or requiring a model endpoint:

```bash
python -m pip install verirepro

verirepro doctor --json
verirepro plan 2103.00020v1
verirepro reproduce 2103.00020v1 --no-execute --no-llm
```

To install a deterministic version pin instead, use a version-neutral form:

```bash
python -m pip install "verirepro==<version>"
```

Specific release pins are recorded in each GitHub Release's notes; the PyPI metadata of a released version is immutable and never changes after publication.

Before allowing third-party experiment code to execute, run:

```bash
verirepro doctor --strict
```

Add `--require-llm` only when model-assisted analysis is required. Docker is an execution boundary, not a formal sandbox proof; intentionally hostile repositories should additionally use disposable infrastructure.

## What a run produces

A reproduction workspace can preserve:

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

The pipeline is intentionally split into orchestration, deterministic policy, execution, verification, and reporting layers so that verdict logic is not hidden inside runtime mechanics.

```text
Paper
  ↓
page-grounded claims
  ↓
repository / dataset evidence
  ↓
repository-grounded execution plan
  ↓
Git + Python + dependency + CUDA provenance
  ↓
Docker execution boundary
  ↓
metrics + Figure/Table/file evidence
  ↓
PASS / FAIL / PARTIAL + evidence bundle
```

## Release certification evidence

Certification is measured on **GitHub-hosted runners only**. This public repository never uses maintainer-owned self-hosted runners, private runner labels, or runner groups for CI, validation, certification, or publishing. Releases are source-bound to the exact canonical `main` source and its signed annotated tag; no private certification chain is ever claimed as this repository's own.

| Mechanism | Policy |
| --- | --- |
| CI / validation / certification runners | GitHub-hosted (`ubuntu-latest`) only |
| Certification path | exact canonical `main` → fresh validation → sanitized artifact → explicit evidence-only promotion |
| Release-source fingerprint | SHA-256 over release-relevant sources (`scripts/release_source_check.py`) |
| Publisher delivery | protected `pypi` environment; OIDC Trusted Publishing only |
| Evidence records | [docs/EVIDENCE.md](docs/EVIDENCE.md) and the matching GitHub Release |

The exact certified source identity, release-source fingerprint, validation run, and evidence commit for each release are recorded in [docs/EVIDENCE.md](docs/EVIDENCE.md) and the matching GitHub Release, rather than embedded as release-state prose in this package description. Run IDs inside sanitized evidence remain provenance-correlation fields. Public verification relies on the committed, SHA-256-bound files under `benchmarks/`, not on machine identity.

These are bounded release measurements, not a claim that arbitrary papers are zero-config reproducible. The 15-paper gate measures discovery/evidence and bounded planning; it does not claim that all 15 papers were fully reproduced. The governance seed intentionally remains `PARTIAL` because no independent scientific comparison is authorized for it; successful process execution is not promoted into scientific truth. See [docs/EVIDENCE.md](docs/EVIDENCE.md) for provenance, scope, and limits.

## Verdict semantics

- **PASS** — execution completed and every available evidence-authorized scientific comparison passed.
- **FAIL** — a required input/environment/execution stage failed, host-side safety verification failed, or an evidence-authorized metric/artifact comparison failed.
- **PARTIAL** — no hard pipeline failure occurred, but available evidence is insufficient to establish scientific `PASS` or `FAIL`.

`PARTIAL` is intentional. VeriRepro does not convert “the script exited 0” into “the paper was reproduced.”

## Evidence authority

A third-party repository may describe **how to run itself**, but it is not automatically trusted to define the scientific truth used to certify itself.

`verirepro.yaml` / `.verirepro.yaml` may request execution configuration. Repository-authored expected metrics and reference artifacts remain outside automatic scientific authority unless a human explicitly opts in:

```bash
verirepro reproduce 2103.00020v1 --trust-repository-contract
```

That flag grants scientific-contract authority only. It does not grant network access, GPU access, host filesystem access, host commands, or credentials.

Experiment output enters automatic scalar comparison only through an explicit final-result marker such as:

```python
print("VERIREPRO_METRIC accuracy=0.908")
```

Arbitrary training-log strings are not treated as final scientific evidence.

## Security model

VeriRepro handles untrusted paper URLs/text, model output, Git repositories, manifests, dataset/model URLs, artifact paths, and experiment output.

The final research-code runtime uses Docker with:

- explicit non-root UID:GID;
- read-only root filesystem;
- bounded writable `/workspace` and `/tmp` tmpfs overlays;
- dropped Linux capabilities and `no-new-privileges`;
- init, PID, CPU, and memory limits;
- bounded stdout/stderr capture;
- network disabled unless both repository request and user `--allow-network` authorization are present;
- GPU unavailable unless both repository request and user `--allow-gpu` authorization are present;
- no LiteLLM credentials inside the experiment container.

Host-side paper/dataset/model downloads have address, redirect, path, byte/count, and integrity controls. Repository acquisition is restricted to canonical HTTPS GitHub URLs with conservative refs and disabled Git `file`/`ext` transports.

For exact boundaries and residual risks, read [SECURITY.md](SECURITY.md) and [docs/TRUST_MODEL.md](docs/TRUST_MODEL.md).

## Real-paper corpus

`benchmarks/real-paper-smoke.json` contains 15 public papers across vision, NLP, computational science, scientific ML, and quantum-computing domains. Every arXiv input is pinned to an explicit revision.

Run the deterministic discovery/evidence gate:

```bash
python scripts/run_real_paper_smoke.py \
  --require-top1 \
  --require-evidence
```

Run bounded real-repository planning without third-party experiment execution:

```bash
python scripts/run_real_paper_smoke.py \
  --require-top1 \
  --require-evidence \
  --inspect-repositories \
  --max-cases 3
```

See [docs/REAL_PAPER_SMOKE.md](docs/REAL_PAPER_SMOKE.md).

## ReproBench

VeriRepro exposes an agent-agnostic ReproBench JSON/process boundary without requiring a sibling source checkout.

```bash
verirepro-reprobench task.json --output result.json
verirepro-reprobench-summary results/*.json --output summary.json
```

The adapter records outcome, environment-build and execution status, grounded metric/artifact comparisons, expected-artifact coverage, failure taxonomy, runtime, provenance, explicit operator interventions, and bounded provider telemetry when available.

Task JSON is untrusted: local/file/insecure-HTTP paper sources are rejected, paths are confined, files are size-bounded, symlinks and non-standard `NaN`/`Infinity` JSON are rejected, and unknown fields are recorded but never executed.

See [docs/REPROBENCH.md](docs/REPROBENCH.md).

## LiteLLM / OpenAI-compatible models

Model-assisted analysis is optional. VeriRepro talks to an OpenAI-compatible endpoint and does not require a provider SDK.

```bash
export VERIREPRO_LITELLM_BASE_URL="https://your-litellm.example.com"
export VERIREPRO_LITELLM_API_KEY="..."
export VERIREPRO_LITELLM_MODEL="research-model"
```

Disable model reasoning while retaining deterministic stages:

```bash
verirepro reproduce 2103.00020v1 --no-llm
```

There is intentionally no `--api-key` CLI argument. Credentials remain host-side and are excluded from third-party experiment containers and release evidence.

## Python API

```python
import verirepro

report = verirepro.reproduce("2103.00020v1", execute=False, use_llm=False)
print(report.status)
```

`python -m verirepro` is supported. The installed `verirepro` package is PEP 561 typed; `reproagent` remains a 0.x compatibility/implementation namespace.

## Development and contribution model

For contributor installation from a checkout:

```bash
git clone https://github.com/XiantingWu/VeriRepro.git
cd VeriRepro
python -m pip install -e '.[dev]'
```

Local development checks:

```bash
python -m pip install -e '.[dev]'
ruff check src tests scripts
ruff format --check src tests scripts
mypy
pytest -q --cov=reproagent --cov=verirepro --cov-branch
python scripts/history_scan.py
python scripts/release_check.py
python scripts/launch_surface_check.py
```

External/fork pull requests receive **GitHub-hosted PR CI** on ephemeral runners with read-only permissions and no repository secrets. PR CI is quality/compatibility CI; manual GitHub-hosted validation certifies only the exact canonical `main` SHA. Validation publishes only sanitized evidence artifacts, which are promoted through an explicit evidence-only PR.

GitHub-hosted CI is the sole automated quality/validation lane. PyPI Trusted Publishing/OIDC delivery in `publish.yml` is a separate release-only delivery boundary.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before sending a change. For reproduction help, use [SUPPORT.md](SUPPORT.md). Security-sensitive findings belong in GitHub's private Security advisory flow, not a public issue.

## Current limitations

- General figure comparison is visual/pixel-based, not semantic plot understanding.
- Automatic PDF Figure/Table crop-to-output matching is incomplete.
- Environment reconstruction cannot make unavailable or underspecified upstream dependencies reproducible.
- NVIDIA/CUDA hardware execution is not currently part of the public GitHub-hosted release-certification matrix.
- Repository checkout does not currently have a hard transfer/working-tree byte quota.
- Persistent experiment output has no portable hard filesystem quota; `--output-backend ephemeral` is available for less-trusted writers.
- Dependency/image builds interact with the Docker daemon before the final non-root research-runtime boundary; hostile builds require stronger isolation.
- Current ReproBench evidence demonstrates its pinned seed cases only.

## Documentation

### Getting Started

- [Getting started](docs/GETTING_STARTED.md)

### Architecture

- [Architecture](docs/ARCHITECTURE.md)

### Trust / Security

- [Trust model](docs/TRUST_MODEL.md)
- [Security policy](SECURITY.md)

### Environment / GPU

- [Environment](docs/ENVIRONMENT.md)
- [Environment managers](docs/ENVIRONMENT_MANAGERS.md)
- [GPU](docs/GPU.md)

### Datasets / Models

- [Real-paper smoke](docs/REAL_PAPER_SMOKE.md)
- [Datasets](docs/DATASETS.md)
- [Model artifacts](docs/MODEL_ARTIFACTS.md)
- [Outputs](docs/OUTPUTS.md)
- [LiteLLM](docs/LITELLM.md)

### ReproBench

- [ReproBench](docs/REPROBENCH.md)

### Evidence

- [Canonical identity](docs/CANONICAL_IDENTITY.md)
- [Release evidence](docs/EVIDENCE.md)

### Publishing / Signing

- [Publishing](docs/PUBLISHING.md)
- [Release signing](docs/RELEASE_SIGNING.md)

### Schemas

- [Schemas](docs/SCHEMAS.md)

### Support / Contribution

- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Support](SUPPORT.md)

## License

Apache-2.0. See [LICENSE](LICENSE).

For academic use, see [CITATION.cff](CITATION.cff).
