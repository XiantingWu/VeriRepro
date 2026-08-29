from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from .config import ArtifactSpec
from .models import ArtifactComparison, OutputArtifact

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".ppm"}
_TABLE_SUFFIXES = {".csv", ".tsv"}
_DEFAULT_MAX_OUTPUT_ENTRIES = 8192
_DEFAULT_MAX_OUTPUT_FILES = 4096
_DEFAULT_MAX_OUTPUT_FILE_BYTES = 1024 * 1024 * 1024
_DEFAULT_MAX_TOTAL_OUTPUT_BYTES = 4 * 1024 * 1024 * 1024
_DEFAULT_MAX_ARTIFACT_COMPARE_BYTES = 128 * 1024 * 1024
_DEFAULT_MAX_TABLE_BYTES = 32 * 1024 * 1024
_DEFAULT_MAX_TABLE_CELLS = 1_000_000
_DEFAULT_MAX_IMAGE_PIXELS = 25_000_000


class ArtifactSecurityError(RuntimeError):
    """Raised when host-side output/artifact processing exceeds a safety budget."""


def _positive_env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ArtifactSecurityError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ArtifactSecurityError(f"{name} must be positive")
    return value


def _safe_path(base: Path, relative: str) -> Path:
    candidate = (base / relative).resolve()
    root = base.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact path escapes allowed root: {relative}") from exc
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _output_limits() -> tuple[int, int, int, int]:
    return (
        _positive_env_int("VERIREPRO_MAX_OUTPUT_ENTRIES", _DEFAULT_MAX_OUTPUT_ENTRIES),
        _positive_env_int("VERIREPRO_MAX_OUTPUT_FILES", _DEFAULT_MAX_OUTPUT_FILES),
        _positive_env_int("VERIREPRO_MAX_OUTPUT_FILE_BYTES", _DEFAULT_MAX_OUTPUT_FILE_BYTES),
        _positive_env_int("VERIREPRO_MAX_TOTAL_OUTPUT_BYTES", _DEFAULT_MAX_TOTAL_OUTPUT_BYTES),
    )


def index_outputs(output_dir: Path) -> tuple[OutputArtifact, ...]:
    if not output_dir.exists():
        return ()
    if output_dir.is_symlink():
        raise ArtifactSecurityError("output directory must not be a symbolic link")

    entry_limit, file_limit, file_byte_limit, total_byte_limit = _output_limits()
    root = output_dir.resolve(strict=True)
    items: list[OutputArtifact] = []
    entries_seen = 0
    total_bytes = 0

    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        safe_dirs: list[str] = []
        for name in sorted(dirnames):
            candidate = directory_path / name
            if not candidate.is_symlink():
                safe_dirs.append(name)
        dirnames[:] = safe_dirs
        filenames.sort()

        entries_seen += len(safe_dirs) + len(filenames)
        if entries_seen > entry_limit:
            raise ArtifactSecurityError(
                f"output tree exceeds host entry limit {entry_limit}; "
                "raise VERIREPRO_MAX_OUTPUT_ENTRIES explicitly if this is intentional"
            )

        for name in filenames:
            path = directory_path / name
            if path.is_symlink():
                continue
            try:
                resolved = path.resolve(strict=True)
                relative = resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if not resolved.is_file():
                continue

            if len(items) >= file_limit:
                raise ArtifactSecurityError(
                    f"output tree exceeds host file-count limit {file_limit}; "
                    "raise VERIREPRO_MAX_OUTPUT_FILES explicitly if this is intentional"
                )
            size = resolved.stat().st_size
            if size > file_byte_limit:
                raise ArtifactSecurityError(
                    f"output artifact {relative.as_posix()!r} exceeds host per-file limit "
                    f"{file_byte_limit} bytes; raise VERIREPRO_MAX_OUTPUT_FILE_BYTES explicitly if intentional"
                )
            total_bytes += size
            if total_bytes > total_byte_limit:
                raise ArtifactSecurityError(
                    f"output artifacts exceed host cumulative read limit {total_byte_limit} bytes; "
                    "raise VERIREPRO_MAX_TOTAL_OUTPUT_BYTES explicitly if intentional"
                )

            suffix = resolved.suffix.lower()
            if suffix in _IMAGE_SUFFIXES:
                kind = "figure"
            elif suffix in _TABLE_SUFFIXES:
                kind = "table"
            else:
                kind = "file"
            items.append(
                OutputArtifact(
                    path=relative.as_posix(),
                    kind=kind,
                    size_bytes=size,
                    sha256=_sha256(resolved),
                )
            )
    return tuple(items)


def _guard_compare_file(path: Path, *, label: str, limit: int | None = None) -> int:
    if path.is_symlink():
        raise ArtifactSecurityError(f"{label} artifact must not be a symbolic link")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ArtifactSecurityError(f"could not stat {label} artifact") from exc
    effective_limit = limit or _positive_env_int(
        "VERIREPRO_MAX_ARTIFACT_COMPARE_BYTES", _DEFAULT_MAX_ARTIFACT_COMPARE_BYTES
    )
    if size > effective_limit:
        raise ArtifactSecurityError(
            f"{label} artifact exceeds host comparison limit {effective_limit} bytes"
        )
    return size


def _figure_similarity(reference: Path, reproduced: Path) -> tuple[float, str]:
    _guard_compare_file(reference, label="reference figure")
    _guard_compare_file(reproduced, label="reproduced figure")
    pixel_limit = _positive_env_int("VERIREPRO_MAX_IMAGE_PIXELS", _DEFAULT_MAX_IMAGE_PIXELS)
    with Image.open(reference) as ref_image, Image.open(reproduced) as rep_image:
        ref_size = ref_image.size
        rep_size = rep_image.size
        if ref_size[0] * ref_size[1] > pixel_limit:
            raise ArtifactSecurityError(f"reference figure exceeds host pixel limit {pixel_limit}")
        if rep_size[0] * rep_size[1] > pixel_limit:
            raise ArtifactSecurityError(f"reproduced figure exceeds host pixel limit {pixel_limit}")
        normalized_size = (128, 128)
        ref = ref_image.convert("RGB").resize(normalized_size, Image.Resampling.LANCZOS)
        rep = rep_image.convert("RGB").resize(normalized_size, Image.Resampling.LANCZOS)
        ref_bytes = ref.tobytes()
        rep_bytes = rep.tobytes()

    squared_error = 0.0
    count = 0
    for left, right in zip(ref_bytes, rep_bytes, strict=False):
        squared_error += float(left - right) ** 2
        count += 1
    rmse = math.sqrt(squared_error / max(count, 1))
    score = max(0.0, min(1.0, 1.0 - rmse / 255.0))
    detail = (
        f"normalized RGB similarity={score:.4f}; "
        f"reference={ref_size[0]}x{ref_size[1]}, reproduced={rep_size[0]}x{rep_size[1]}"
    )
    return score, detail


def _read_table(path: Path, *, label: str) -> list[list[str]]:
    table_byte_limit = _positive_env_int("VERIREPRO_MAX_TABLE_BYTES", _DEFAULT_MAX_TABLE_BYTES)
    _guard_compare_file(path, label=label, limit=table_byte_limit)
    cell_limit = _positive_env_int("VERIREPRO_MAX_TABLE_CELLS", _DEFAULT_MAX_TABLE_CELLS)
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows: list[list[str]] = []
    cells = 0
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.reader(handle, delimiter=delimiter):
                cells += len(row)
                if cells > cell_limit:
                    raise ArtifactSecurityError(
                        f"{label} table exceeds host cell limit {cell_limit}"
                    )
                rows.append(list(row))
    except csv.Error as exc:
        raise ArtifactSecurityError(f"could not parse {label} table safely: {exc}") from exc
    return rows


def _number(value: str) -> float | None:
    try:
        return float(value.strip())
    except ValueError:
        return None


def _project_table_columns(
    rows: list[list[str]],
    columns: tuple[str, ...],
    *,
    label: str,
) -> list[list[str]]:
    if not columns:
        return rows
    if not rows:
        raise ArtifactSecurityError(f"{label} table is empty; cannot select columns")
    header = [value.strip() for value in rows[0]]
    indices: list[int] = []
    for column in columns:
        matches = [index for index, value in enumerate(header) if value == column]
        if len(matches) != 1:
            raise ArtifactSecurityError(
                f"{label} table must contain exactly one column named {column!r}"
            )
        indices.append(matches[0])
    projected: list[list[str]] = [list(columns)]
    for row_number, row in enumerate(rows[1:], start=2):
        if any(index >= len(row) for index in indices):
            raise ArtifactSecurityError(
                f"{label} table row {row_number} is shorter than the selected columns"
            )
        projected.append([row[index] for index in indices])
    return projected


def _table_similarity(
    reference: Path,
    reproduced: Path,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
    columns: tuple[str, ...] = (),
) -> tuple[float, str]:
    ref_rows = _project_table_columns(
        _read_table(reference, label="reference"),
        columns,
        label="reference",
    )
    rep_rows = _project_table_columns(
        _read_table(reproduced, label="reproduced"),
        columns,
        label="reproduced",
    )
    max_rows = max(len(ref_rows), len(rep_rows))
    total = 0
    matches = 0

    for row_index in range(max_rows):
        ref_row = ref_rows[row_index] if row_index < len(ref_rows) else []
        rep_row = rep_rows[row_index] if row_index < len(rep_rows) else []
        max_cols = max(len(ref_row), len(rep_row))
        for column_index in range(max_cols):
            total += 1
            if column_index >= len(ref_row) or column_index >= len(rep_row):
                continue
            left = ref_row[column_index].strip()
            right = rep_row[column_index].strip()
            left_number = _number(left)
            right_number = _number(right)
            if left_number is not None and right_number is not None:
                tolerance = absolute_tolerance + relative_tolerance * max(
                    abs(left_number), abs(right_number)
                )
                if abs(left_number - right_number) <= tolerance:
                    matches += 1
            elif left == right:
                matches += 1

    score = matches / total if total else 1.0
    ref_shape = (len(ref_rows), max((len(row) for row in ref_rows), default=0))
    rep_shape = (len(rep_rows), max((len(row) for row in rep_rows), default=0))
    detail = (
        f"cell agreement={matches}/{total} ({score:.4f}); "
        f"reference_shape={ref_shape[0]}x{ref_shape[1]}, "
        f"reproduced_shape={rep_shape[0]}x{rep_shape[1]}"
        + (f"; selected_columns={','.join(columns)}" if columns else "")
    )
    return score, detail


def compare_artifact(spec: ArtifactSpec, repository: Path, output_dir: Path) -> ArtifactComparison:
    reference = _safe_path(repository, spec.reference)
    reproduced = _safe_path(output_dir, spec.reproduced)
    if not reference.is_file():
        return ArtifactComparison(
            name=spec.name,
            kind=spec.kind,
            reference=spec.reference,
            reproduced=spec.reproduced,
            score=0.0,
            threshold=spec.threshold,
            passed=False,
            detail="reference artifact is missing",
        )
    if not reproduced.is_file():
        return ArtifactComparison(
            name=spec.name,
            kind=spec.kind,
            reference=spec.reference,
            reproduced=spec.reproduced,
            score=0.0,
            threshold=spec.threshold,
            passed=False,
            detail="reproduced artifact is missing",
        )

    kind = spec.kind.lower()
    if kind == "figure":
        score, detail = _figure_similarity(reference, reproduced)
    elif kind == "table":
        score, detail = _table_similarity(
            reference,
            reproduced,
            absolute_tolerance=spec.absolute_tolerance,
            relative_tolerance=spec.relative_tolerance,
            columns=spec.columns,
        )
    elif kind == "file":
        _guard_compare_file(reference, label="reference file")
        _guard_compare_file(reproduced, label="reproduced file")
        score = 1.0 if _sha256(reference) == _sha256(reproduced) else 0.0
        detail = "SHA-256 match" if score == 1.0 else "SHA-256 mismatch"
    else:
        return ArtifactComparison(
            name=spec.name,
            kind=spec.kind,
            reference=spec.reference,
            reproduced=spec.reproduced,
            score=0.0,
            threshold=spec.threshold,
            passed=False,
            detail=f"unsupported artifact kind: {spec.kind}",
        )

    return ArtifactComparison(
        name=spec.name,
        kind=kind,
        reference=spec.reference,
        reproduced=spec.reproduced,
        score=score,
        threshold=spec.threshold,
        passed=score >= spec.threshold,
        detail=detail,
    )


def compare_artifacts(
    specs: tuple[ArtifactSpec, ...],
    repository: Path,
    output_dir: Path,
) -> tuple[ArtifactComparison, ...]:
    return tuple(compare_artifact(spec, repository, output_dir) for spec in specs)


def write_artifact_results(
    comparisons: tuple[ArtifactComparison, ...],
    outputs: tuple[OutputArtifact, ...],
    destination: Path,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "comparisons": [asdict(item) for item in comparisons],
        "outputs": [asdict(item) for item in outputs],
    }
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return destination
