# Model and checkpoint artifacts

VeriRepro 0.8 can materialize explicit model/checkpoint files on the host before an experiment starts and mount the verified files read-only at `/models`.

This feature is intentionally narrower than a generic model hub client. It solves one reproducibility problem: a paper repository can declare the exact external bytes required by its experiment without gaining implicit container networking or write access to the source artifact.

## Manifest contract

Model artifacts live under `model_artifacts` in `verirepro.yaml` and **must include SHA-256**.

```yaml
version: 1
experiment:
  command: python reproduce.py

model_artifacts:
  - name: encoder-checkpoint
    url: https://example.org/releases/encoder.bin
    filename: encoder.bin
    sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
    max_bytes: 2147483648
```

Supported resolver forms in 0.8 are:

- direct HTTPS URL;
- Zenodo record + file;
- public Hugging Face model repository + explicit non-`main` revision + path.

Example structured Hugging Face declaration:

```yaml
model_artifacts:
  - name: weights
    provider: huggingface
    repo_id: organization/model-name
    revision: 0123456789abcdef0123456789abcdef01234567
    path: model.safetensors
    filename: model.safetensors
    sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

The structured Hugging Face model resolver is public-download-only in 0.8. VeriRepro does not forward `HF_TOKEN`, model-hub credentials, or any other host secret into the experiment container.

## Execution contract

The resolver runs before Docker execution:

1. parse and bound the untrusted manifest;
2. resolve the remote file on the host;
3. enforce SSRF/redirect/filename/symlink/byte controls;
4. verify SHA-256;
5. optionally reuse the content-addressed host cache only after checksum verification;
6. write sanitized `model-artifact-provenance.json`;
7. mount the materialized directory as `/models:ro`;
8. expose `VERIREPRO_MODEL_DIR=/models` and the 0.x compatibility alias `REPROAGENT_MODEL_DIR=/models`.

The experiment still receives `--network none` unless the repository separately requests network access and the operator explicitly supplies `--allow-network`. Declaring a model artifact does not authorize network access.

## Current host budgets

Model artifacts reuse the hardened file materializer and its host-owned download/cache ceilings in 0.8. A repository-provided `max_bytes` can only lower its own file ceiling; it cannot raise the host ceiling. Operators may explicitly raise host limits through the existing `VERIREPRO_MAX_DATASET_BYTES`, `VERIREPRO_MAX_TOTAL_DATASET_BYTES`, and cache-budget environment variables when a reviewed checkpoint genuinely requires it.

Dedicated model-artifact budget variable names may be introduced in a future compatibility revision; the current security boundary is already host-owned.

## Provenance

`model-artifact-provenance.json` records provider identity, sanitized source identity, filename, observed byte count, observed and expected SHA-256, materialization mode, and cache status. URL query parameters and host-local cache paths are not part of the persisted source identity.

## Non-goals

0.8 does not claim:

- generic checkpoint format interpretation;
- automatic architecture selection;
- private Hugging Face repository authentication;
- model license acceptance on a user's behalf;
- GPU/CUDA support merely because a checkpoint is present.

Those remain explicit, separately validated concerns.
