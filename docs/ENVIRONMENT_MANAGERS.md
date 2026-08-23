# Environment manager support

VeriRepro separates **environment detection**, **environment realization**, and **reproducibility claims**. A repository having an environment file does not by itself make a rebuild deterministic.

## Support matrix

| Repository input | Strategy | Realization | Reproducibility note |
| --- | --- | --- | --- |
| `uv.lock` + `pyproject.toml` | `uv` | `uv sync --frozen --no-dev` | Lock-bound when the repository commit is pinned. |
| `poetry.lock` + `pyproject.toml` | `poetry` | Poetry install from the committed lock/project | Lock-bound when the repository commit is pinned. |
| `conda-lock.yml` or `conda-lock.yaml` | `conda-lock` | `conda-lock 4.0.2` into a dedicated micromamba environment | Lock-bound when the repository commit is pinned. |
| `Pipfile` + `Pipfile.lock` | `pipenv-lock` | Pipenv system install with `--deploy --ignore-pipfile` | Lock-bound when the repository commit is pinned. |
| `requirements.txt` | `requirements` | Wheel-first pip install, source-build fallback | Strong only when direct requirements are sufficiently pinned; otherwise drift is reported. |
| `environment.yml` / `environment.yaml` without conda-lock | `conda` | Fresh micromamba solve | May drift. VeriRepro reports this explicitly and does not label it lock-bound. |
| `Pipfile` without `Pipfile.lock` | `pipenv` | Fresh Pipenv solve with `--skip-lock` | May drift. VeriRepro reports this explicitly. |
| `pyproject.toml` / `setup.py` without a supported lock | `pyproject` / `setup` | pip project install | Depends on the project's own dependency constraints. |

## Conda lock boundary

For unified conda-lock files, VeriRepro uses a digest-pinned `mambaorg/micromamba:2.9.0-debian13-slim` image and a pinned `conda-lock==4.0.2` installer. The lock is installed into a dedicated `verirepro` environment rather than the image's pre-existing `base` environment. Runtime activation uses micromamba's `ENV_NAME=verirepro` mechanism.

The temporary tool environment used only to run `conda-lock` is removed in a separate root-owned Docker build layer. The final research-code runtime returns to the unprivileged runtime identity; this cleanup step does not grant experiment code root privileges.

A plain `environment.yml` is deliberately different: it requires solving dependency constraints again. VeriRepro supports that path for compatibility but records a warning because it is not equivalent to a lock-bound reconstruction.

## Pipenv lock boundary

For `Pipfile.lock`, VeriRepro installs with:

```text
PIPENV_DONT_LOAD_ENV=1 PIPENV_NOSPIN=1 pipenv install --system --deploy --ignore-pipfile
```

This prevents a repository `.env` file from silently injecting build settings and refuses to relock from `Pipfile` during the deterministic path.

VeriRepro pins the Pipenv interpreter used by the builder. Python 3.10+ uses the currently validated `2026.7.1` path; Python 3.8/3.9 retains the validated `2024.4.1` compatibility path instead of silently dropping older repository support during environment reconstruction.

## Precedence

When a repository contains overlapping dependency declarations, deterministic lock-aware inputs take precedence before looser fallbacks:

```text
uv -> poetry -> conda-lock -> pipenv-lock -> requirements -> pyproject -> setup -> conda -> pipenv -> none
```

The selected strategy and dependency files are included in the environment plan and environment fingerprint.

## What 0.8 validates

The 0.8 automated release validation includes:

- deterministic regression tests for strategy precedence, Python requirement parsing, warnings, tool pins, and generated Dockerfiles;
- the complete VeriRepro unit suite;
- a real `Pipfile.lock` generation followed by Docker image build and offline container execution;
- a real `conda-lock.yml` generation for `linux-aarch64`, Docker image build, and offline container execution;
- standalone package/export/build/install checks;
- ReproBench regression proving environment changes do not silently alter verdict semantics.

These checks establish that the supported environment reconstruction paths build and execute their bounded fixtures. They do **not** claim that arbitrary research repositories are reproducible or that successful program execution establishes scientific agreement.

For intentionally hostile dependency/build inputs, use additional build isolation. The non-root/read-only experiment runtime is a later boundary and does not make Docker image construction rootless.
