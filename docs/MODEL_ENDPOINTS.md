# Model endpoints

Optional model-assisted analysis through an OpenAI-compatible HTTP endpoint.

## Overview

VeriRepro's model reasoning is optional. It is provided through a provider-neutral OpenAI-compatible HTTP client that talks directly to a configured model endpoint and does not require a model-provider SDK.

Without a configured model endpoint, deterministic discovery and planning still run. Model-assisted analysis adds structured paper facts, metrics, repositories, and ambiguity auditing on top of the deterministic pipeline.

## Preferred configuration

Configure an OpenAI-compatible endpoint with the `VERIREPRO_LLM_*` environment variables:

```bash
export VERIREPRO_LLM_BASE_URL="https://model-gateway.example.com"
export VERIREPRO_LLM_API_KEY="..."
export VERIREPRO_LLM_MODEL="research-model"
```

Optional:

```bash
export VERIREPRO_LLM_TIMEOUT=120
export VERIREPRO_LLM_REASONING_EFFORT=medium
```

`VERIREPRO_LLM_TIMEOUT` defaults to 120 seconds and accepts only integer values in `[1, 3600]`. Zero, negative, non-integer, and larger values are rejected as configuration errors before any HTTP request is attempted. `doctor` reports configuration errors without echoing the private endpoint URL or credential value.

## Endpoint contract

`VERIREPRO_LLM_BASE_URL` must point to an OpenAI-compatible chat-completions HTTP surface. The base URL may point to:

- the endpoint root;
- a `/v1` path;
- a full `/v1/chat/completions` path.

VeriRepro normalizes the chat-completions endpoint for the configured base URL.

## Optional model reasoning

Model-assisted analysis is controlled per run:

```bash
verirepro reproduce 2103.00020v1 --no-llm --no-execute
```

- `--no-llm` disables optional model-assisted paper intelligence while retaining deterministic discovery/planning logic.
- `--model` overrides the configured model for one run.
- `--require-llm` (with `verirepro doctor`) treats model-endpoint configuration as required for readiness instead of optional.

## Trust boundary

Model output is a proposal, not scientific ground truth and not an execution capability. It never grants:

- scientific authority;
- network access;
- GPU access;
- filesystem access;
- credentials;
- repository contract authority.

Every concrete paper claim should include a 1-based page and short quote. VeriRepro verifies the quote against extracted page text and labels it:

- `verified` — normalized quote occurs on the claimed page;
- `approximate` — strong token overlap survives PDF extraction artifacts;
- `unverified` — the citation cannot be grounded.

Only verified or approximate metric claims can participate in automated scientific comparison. Non-finite model-proposed scientific values such as `NaN` or `Infinity` are discarded before they can enter `paper-intelligence.json`; non-finite tolerances fall back to the finite default. Serialized intelligence evidence is strict JSON and refuses non-standard numeric constants.

Repository execution planning has an additional deterministic boundary: a model cannot invent an entrypoint or freely emit shell. The selected entrypoint, repository evidence, documented command, and constrained syntax are checked before a model-derived plan can execute.

## Credentials

Model-provider credentials remain host-side and are environment-only; there is no `--api-key` command-line option.

Model-provider credentials are not passed into experiment containers. Maintainer integration workflows should scope secrets only to the steps that actually need model access and must never expose them to public fork pull-request execution.

A separately configured model endpoint also does not inherit an unrelated `OPENAI_API_KEY` by accident: namespace-aware API-key selection only forwards `OPENAI_API_KEY` when the endpoint is entered through the OpenAI configuration path.

## Usage telemetry

Provider-reported model usage telemetry is recorded only when the endpoint exposes it: request/response model identifiers, request count, latency, token counts, and provider-reported cost. Telemetry is bounded, non-secret, and does not grant scientific authority. Endpoint URLs, API keys, authorization headers, prompts, and response content are never captured in telemetry or release evidence.

## Output

With model reasoning configured, a full run can add:

```text
paper-intelligence.json
repository-plan.json
```

The final `report.md` exposes evidence anchors, ambiguity audit, repository execution evidence, environment provenance, metrics, and declared artifact comparisons.