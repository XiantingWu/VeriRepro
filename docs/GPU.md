# GPU authorization boundary

VeriRepro treats GPU access as a **host capability**, not as something a third-party repository can grant itself.

## Two-key authorization

A repository may request GPU access in its manifest:

```yaml
version: 1
experiment:
  command: python reproduce.py
  gpu: true
```

That request is not authorization. The user must independently opt in:

```bash
verirepro reproduce paper.pdf --allow-gpu
```

GPU device access is effective only when both conditions are true:

```text
manifest experiment.gpu == true
AND
user supplied --allow-gpu
```

The same fail-closed rule applies to older or partial objects: a missing GPU request or a missing GPU diagnostic signal is interpreted as `false`, never as permission.

## Detection is not permission

Repository inspection may set `gpu_likely` after observing CUDA-related dependencies or source usage. This is diagnostic evidence only. It does not add Docker GPU devices and it does not bypass the manifest/user authorization pair.

Therefore all of the following remain CPU-only:

- CUDA signals are detected but the manifest does not request GPU access;
- the manifest requests GPU access but the user does not pass `--allow-gpu`;
- the user passes `--allow-gpu` but the manifest does not request GPU access;
- legacy or partial manifest/plan objects omit GPU fields.

## Docker boundary

When GPU access is explicitly authorized, VeriRepro requests configured Docker GPU devices with:

```text
--gpus all
```

This does not relax the rest of the runtime boundary. The container still retains the normal restrictions and limits, including explicit non-root identity, read-only root filesystem, bounded writable tmpfs overlays, capability dropping, `no-new-privileges`, PID/CPU/memory limits, bounded log capture, timeout cleanup, and disabled networking unless network access is separately requested and separately authorized.

GPU authorization and network authorization are independent. Authorizing a GPU does not enable the network.

## What 0.8 validates

The 0.8 automated release gates validate the authorization contract deterministically:

- strict boolean parsing of `experiment.gpu`;
- the two-key truth table;
- CPU-only defaults and compatibility fallbacks;
- Docker command construction adds `--gpus all` only after explicit authorization;
- existing capability/security/network flags remain present;
- the complete unit suite passes;
- standalone package/build/install checks pass;
- the CPU ReproBench seed continues to pass, showing that the GPU capability does not alter the default CPU execution path.

These checks validate **authorization semantics and command construction**. They are not NVIDIA hardware certification.

## What 0.8 does not claim yet

VeriRepro 0.8 has not been release-certified on NVIDIA/CUDA hardware. It therefore does **not** claim that arbitrary CUDA research repositories can build or execute successfully merely because the device-authorization contract exists.

A complete NVIDIA/CUDA execution profile still requires, at minimum:

- dedicated NVIDIA-capable trusted infrastructure;
- validated NVIDIA Container Toolkit/device availability;
- explicit CUDA/driver compatibility policy;
- digest-pinned CUDA base-image profiles where appropriate;
- real GPU build/run fixtures and failure semantics;
- proof that GPU enablement does not weaken existing sandbox/network/credential boundaries.

Until those gates are measured, VeriRepro should describe GPU support as an **explicit device-authorization boundary**, not as universal CUDA environment reconstruction.
