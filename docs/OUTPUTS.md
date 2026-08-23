# Experiment output policy

VeriRepro separates scientific output handling from the container's other writable paths. The experiment always sees `VERIREPRO_OUTPUT_DIR=/repro-output` (and the 0.x compatibility alias `REPROAGENT_OUTPUT_DIR`). The operator chooses how that path is backed.

## Persistent output (default)

```bash
verirepro reproduce <paper> --output-backend persistent
```

`/repro-output` is a run-scoped host bind. Files survive the container and can be indexed, hashed, compared against explicitly trusted artifact contracts, and included in the evidence bundle.

Host-side post-run processing is bounded by file-count, per-file, cumulative-byte, image-pixel, and table-cell limits. Those limits bound VeriRepro's reads and comparisons; they are not a filesystem quota on writes performed by the experiment itself.

Use this mode for repositories you are willing to let write into the run-scoped output directory.

## Ephemeral bounded output

```bash
verirepro reproduce <paper> --output-backend ephemeral
```

`/repro-output` becomes a Docker tmpfs owned by the same explicit non-root UID:GID as the experiment. There is no host output bind. File outputs are discarded automatically when the container exits.

The host-owned byte ceiling is controlled by:

```bash
export VERIREPRO_RUNTIME_OUTPUT_TMPFS_BYTES=1073741824
```

The default is 1 GiB. The value must be a positive integer. Repository content and `verirepro.yaml` cannot raise it.

Ephemeral mode is intended for less-trusted experiments where protecting host disk capacity matters more than retaining generated files. Stdout/stderr remain host-bounded and can still carry deterministic metric markers. File-based artifact comparisons cannot succeed when their reproduced files are intentionally discarded.

Inside the container, `VERIREPRO_OUTPUT_PERSISTENCE` and `REPROAGENT_OUTPUT_PERSISTENCE` are set to either `persistent` or `ephemeral` so an experiment can report its operating mode without discovering host paths.

## What this does not claim

Ephemeral mode is a bounded disposable volume, not a portable hard quota for persistent bind mounts. VeriRepro does not claim that `persistent` mode can prevent a hostile process from filling the underlying host filesystem. For untrusted code, prefer `ephemeral` output and a disposable worker; see `TRUST_MODEL.md` and `SECURITY.md` for the complete boundary.
