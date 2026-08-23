# Dataset declarations and host-download policy

VeriRepro supports three manifest dataset providers in schema version 1. Dataset declarations are repository-controlled input, so host retrieval, cache reuse, and provenance generation are all treated as trust boundaries.

## Direct URL

```yaml
datasets:
  - name: benchmark
    provider: url
    url: https://example.org/benchmark.zip?mirror=primary
    filename: benchmark.zip
    sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
    max_bytes: 2147483648
```

A declared `sha256`, when present, must be exactly 64 hexadecimal characters. URL query strings are used for retrieval but are excluded from committed/run provenance so signed URLs and tokens are not persisted there.

## Hugging Face

```yaml
datasets:
  - name: validation
    provider: huggingface
    repo_id: my-org/my-dataset
    revision: 4f6d2c1
    path: data/validation.parquet
    sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
    max_bytes: 1073741824
```

The generated URL is pinned to the requested revision. For private/gated repositories, `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` is added only to the Hugging Face host request and is not forwarded into experiment containers. Sensitive authorization headers are stripped before any cross-host redirect.

## Zenodo

```yaml
datasets:
  - name: benchmark
    provider: zenodo
    record_id: "12345678"
    file: benchmark.zip
    sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

VeriRepro retrieves public record metadata, locates the named file, then downloads the file URL exposed by the record.

## Host-owned resource limits

`max_bytes` in a repository manifest is a **request**, not authority over the host. The effective per-dataset materialization limit is bounded by both the manifest and host policy:

```text
min(manifest max_bytes, VERIREPRO_MAX_DATASET_BYTES, remaining total-run budget)
```

The defaults are:

```text
VERIREPRO_MAX_DATASET_BYTES        5 GiB per dataset
VERIREPRO_MAX_TOTAL_DATASET_BYTES  10 GiB materialized per run
VERIREPRO_MAX_DATASETS             32 datasets per run
```

A repository can lower its own `max_bytes`, but cannot raise any host ceiling. Users can deliberately raise host limits when needed:

```bash
export VERIREPRO_MAX_DATASET_BYTES=10737418240
export VERIREPRO_MAX_TOTAL_DATASET_BYTES=21474836480
export VERIREPRO_MAX_DATASETS=64
```

All three environment values must be positive integers.

## Content-addressed host cache

Cross-run cache reuse is **off by default**. A host operator enables it by setting an absolute cache directory:

```bash
export VERIREPRO_DATASET_CACHE_DIR=/var/cache/verirepro/datasets
```

The repository cannot choose this path. The configured path must be absolute, must resolve to a real directory, and symbolic-link path components are rejected.

Only datasets with a valid declared SHA-256 are eligible for cross-run cache reuse. VeriRepro never treats “same URL”, “same provider id”, or “same filename” as proof that bytes are identical. Cache entries are addressed by the expected SHA-256 digest.

A cache hit is not trusted blindly. VeriRepro opens cache entries without following symbolic links, copies the entry into the run-scoped dataset destination while enforcing the same effective byte limit, and recomputes SHA-256 before the file can be materialized. Unsafe cache metadata fails closed instead of being followed.

Cache growth is host-bounded. Defaults are:

```text
VERIREPRO_MAX_DATASET_CACHE_BYTES    20 GiB
VERIREPRO_MAX_DATASET_CACHE_ENTRIES  4096 files
```

These environment values must be positive integers. When the cache budget is exhausted, the current run can still use a successfully downloaded/materialized dataset; VeriRepro simply declines to add another new cache entry. An already-valid same-digest cache object is idempotent and does not require another entry slot.

### Concurrent cache users

Cooperating VeriRepro processes serialize shared-cache lookup/store and capacity decisions with a cache-local advisory lock file. The lock file is opened with no-follow semantics, must be a regular file, and is excluded from cache-entry accounting.

Lock acquisition is bounded by a host-owned timeout:

```bash
export VERIREPRO_DATASET_CACHE_LOCK_TIMEOUT_SECONDS=300
```

The value must be a positive integer. If an otherwise legitimate cache lock remains busy until the timeout, VeriRepro bypasses cache reuse for that operation and continues through the normal verified download/materialization path; lock contention never authorizes unverified cache bytes. After a successful download, another bounded lock acquisition is used before a cache store. A timeout there simply leaves the run result uncached.

Capacity checking and creation of a genuinely new cache object occur under the same exclusive lock. Two processes storing the same digest therefore converge on one content entry: the first can report `stored`, while the serialized second writer safely revalidates the existing bytes and reports `already_present` rather than consuming another entry slot.

The shared cache is an optimization, not scientific evidence and not a correctness dependency. Unpinned datasets remain downloadable under the normal host policy, but they are marked uncacheable for cross-run reuse.

## Dataset provenance manifest

When a reproduction declares datasets, the pipeline writes a run-scoped `dataset-provenance.json` next to the other reproduction evidence. Schema version 1 records, per dataset:

- declared name/provider;
- sanitized provider source identity;
- run-local filename;
- materialized byte count;
- observed SHA-256;
- expected SHA-256 when one was declared;
- whether bytes came from a verified existing file, a cache hit, or a download;
- cache outcome such as disabled, hit, stored, already present, bypassed on lock timeout, or not stored because of a host budget/safety condition.

The provenance file deliberately does **not** record host cache paths, credentials, request headers, or URL query strings. Direct-URL provenance keeps only scheme/authority/path. Hugging Face provenance records repository id, revision, and path; Zenodo provenance records record id and file name.

A provenance file documents byte origin/materialization behavior. It does not turn successful data retrieval into a scientific result and does not grant repository-declared expectations authority over the final verdict.

## Security policy

Dataset retrieval happens on the host before the read-only dataset directory is mounted into the experiment container. Because the manifest is untrusted repository content, host downloads are treated as a security boundary.

Controls:

1. HTTPS is required by default. `VERIREPRO_ALLOW_INSECURE_HTTP=1` is an explicit escape hatch intended only for controlled environments.
2. URLs with embedded username/password credentials are rejected.
3. Literal and DNS-resolved non-global IP addresses are rejected.
4. Redirects are followed manually and every redirect target is re-validated before the next request.
5. The host owns the dataset count, per-file bytes, cumulative materialized-byte ceilings, cache entry count, cache bytes, and cache-lock timeout; manifest values cannot raise them.
6. Both `Content-Length` and streamed bytes are checked against the effective remaining run budget.
7. Downloads write to a fresh `.part` file and atomically replace the destination only after success.
8. Symlinked destination or `.part` paths are rejected instead of followed.
9. A declared SHA-256 mismatch fails the dataset stage and deletes the partial file.
10. A previously materialized destination is reused only when a declared SHA-256 matches and the existing path is not a symlink.
11. Cross-run cache reuse requires a declared SHA-256, rehashes every hit, and rejects unsafe cache roots, lock files, and entries instead of following them.
12. Shared-cache capacity decisions and new entry mutation are serialized under a bounded advisory lock; same-digest stores are idempotent and ordinary lock contention falls back to the verified download path.
13. Dataset destination filenames are single components, stay confined to the dataset root, and duplicate destinations are rejected case-insensitively before retrieval.
14. Provenance is written atomically and omits credentials, URL query strings, and host cache paths.

The repository manifest itself is also treated as untrusted input: it must be a regular non-symlink file and is limited to 1 MiB before strict YAML loading.

For high-risk repositories, run VeriRepro itself in an ephemeral VM/worker with outbound network policy. Application-layer checks are defense in depth, not a replacement for infrastructure egress controls.
