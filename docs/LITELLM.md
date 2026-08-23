# LiteLLM integration

VeriRepro uses a provider-neutral OpenAI-compatible HTTP client. It does not import the LiteLLM Python SDK and does not couple the core pipeline to a single model vendor.

## Preferred environment variables

```bash
export VERIREPRO_LITELLM_BASE_URL="https://your-litellm.example.com"
export VERIREPRO_LITELLM_API_KEY="..."
export VERIREPRO_LITELLM_MODEL="your-model-alias"
```

Optional:

```bash
export VERIREPRO_LITELLM_TIMEOUT=120
export VERIREPRO_LITELLM_REASONING_EFFORT=medium
```

`VERIREPRO_LITELLM_TIMEOUT` defaults to 120 seconds and accepts only integer values in `[1, 3600]`. Zero, negative, non-integer, and larger values are rejected as configuration errors before any HTTP request is attempted. `doctor` reports configuration errors without echoing the private gateway URL or credential value.

The standard aliases remain supported:

```text
LITELLM_BASE_URL
LITELLM_API_KEY
LITELLM_MODEL
```

Legacy `REPROAGENT_*` compatibility aliases also remain supported during the 0.x transition:

```text
REPROAGENT_LITELLM_BASE_URL
REPROAGENT_LITELLM_API_KEY
REPROAGENT_LITELLM_MODEL
REPROAGENT_LITELLM_TIMEOUT
REPROAGENT_LITELLM_REASONING_EFFORT
```

`*_BASE_URL` may point to the proxy root, `/v1`, or `/v1/chat/completions`; VeriRepro normalizes the chat-completions endpoint.

## Commands

Run evidence-grounded paper analysis without executing third-party research code, using a pinned paper from the fixed public smoke corpus:

```bash
verirepro reproduce 2103.00020v1 --no-execute
```

Override only the model alias for one run:

```bash
verirepro reproduce 2103.00020v1 --model research-model --no-execute
```

Disable model reasoning entirely while retaining deterministic discovery/planning logic:

```bash
verirepro reproduce 2103.00020v1 --no-llm --no-execute
```

## Trust contract

The model is allowed to propose experiment facts and a constrained repository plan; it is never the source of truth or an authority grant.

Every concrete paper claim should include a 1-based page and short quote. VeriRepro verifies the quote against extracted page text and labels it:

- `verified` — normalized quote occurs on the claimed page;
- `approximate` — strong token overlap survives PDF extraction artifacts;
- `unverified` — the citation cannot be grounded.

Only verified or approximate metric claims can participate in automated scientific comparison. Non-finite model-proposed scientific values such as `NaN` or `Infinity` are discarded before they can enter `paper-intelligence.json`; non-finite tolerances fall back to the finite default. Serialized intelligence evidence is strict JSON and refuses non-standard numeric constants.

Repository execution planning has an additional deterministic boundary: a model cannot invent an entrypoint or freely emit shell. The selected entrypoint, repository evidence, documented command, and constrained syntax are checked before a model-derived plan can execute.

Model output never authorizes experiment network access, GPU access, host filesystem access, credentials, or repository-authored scientific expectations. Those remain separate host-controlled capabilities.

## Secret handling

API keys are intentionally environment-only; there is no `--api-key` command-line option.

LiteLLM credentials are not passed into experiment containers. Maintainer integration workflows should scope secrets only to the steps that actually need model access and must never expose them to public fork pull-request execution.

A separately configured LiteLLM gateway also does not inherit an unrelated `OPENAI_API_KEY` by accident.

## Output

With model reasoning configured, a full run can add:

```text
paper-intelligence.json
repository-plan.json
```

The final `report.md` exposes evidence anchors, ambiguity audit, repository execution evidence, environment provenance, metrics, and declared artifact comparisons.
