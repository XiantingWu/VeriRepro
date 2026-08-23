# Environment intelligence

VeriRepro 0.8 records a machine-readable environment plan before execution so dependency decisions, reproducibility limits, and failures remain inspectable instead of being hidden behind a Docker build log.

## Inputs

Repository inspection can consider `.python-version`, `pyproject.toml`, `requirements.txt`, `uv.lock`, `poetry.lock`, `conda-lock.yml` / `conda-lock.yaml`, `environment.yml` / `environment.yaml`, `Pipfile`, `Pipfile.lock`, setup metadata, notebooks, and bounded source-level CUDA/GPU signals.

Host inspection accepts only real non-symlink files whose resolved paths stay inside the cloned repository root.

## Python resolution

`--python auto` is the default. VeriRepro prefers an explicit repository declaration when it is valid; otherwise it evaluates supported `requires-python` constraints and chooses a compatible supported Python minor. The final decision and its evidence source are written to `environment-plan.json`.

Users can explicitly override the decision when they have reviewed the repository requirement:

```bash
verirepro reproduce paper.pdf --python 3.11
```

Requested or inferred Python minors are validated before they can enter generated Dockerfile content.

## Dependency strategies

VeriRepro distinguishes lock-aware realization from looser reconstruction paths.

Preferred deterministic inputs are evaluated before fallbacks:

```text
uv -> poetry -> conda-lock -> pipenv-lock -> requirements -> pyproject -> setup -> conda -> pipenv -> none
```

Lock-aware paths include:

- `uv.lock` + `pyproject.toml`;
- `poetry.lock` + `pyproject.toml`;
- `conda-lock.yml` / `conda-lock.yaml`;
- `Pipfile.lock` + `Pipfile`.

Unlocked `environment.yml` and `Pipfile` remain supported compatibility paths, but the plan reports that they require a fresh solve and may drift. `requirements.txt`, project metadata, and setup-based installs are only as reproducible as their own constraints.

See `ENVIRONMENT_MANAGERS.md` for realization details and current tool pins.

## Provenance

The environment plan records, when available:

- exact Git commit;
- selected Python version and evidence source;
- dependency strategy and supporting files;
- repository fingerprint;
- environment fingerprint;
- reproducibility grade and warnings;
- GPU/CUDA likelihood signals;
- deterministic entrypoint hints.

These fingerprints are evidence identifiers derived from inspected source/configuration. They are not cryptographic attestations of every byte fetched later during an unlocked dependency solve or image build.

## Build boundary

Environment reconstruction happens during Docker image construction. Third-party package-manager/build hooks may execute at this stage and may need package-index network access.

The final research-code runtime is non-root and read-only, but those runtime controls do **not** make the Docker daemon or dependency/image build rootless. Intentionally hostile build inputs require additional isolation such as a disposable VM, rootless builder, or hardened worker with egress controls.

## GPU/CUDA signals

CUDA/GPU detection is diagnostic only. Signals can include dependency names and bounded source usage such as `torch.cuda` or `.cuda()`.

A GPU hint does not grant a device and does not prove that an experiment cannot run on CPU. Actual GPU access requires both a repository manifest request and independent user `--allow-gpu` authorization. See `GPU.md`.

VeriRepro 0.8 validates the GPU authorization contract and Docker command construction, but does not claim NVIDIA hardware certification until matching NVIDIA-capable trusted infrastructure is measured.
