from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from reproagent.artifacts import (
    ArtifactSecurityError,
    _figure_similarity,
    _guard_compare_file,
    _output_limits,
    _positive_env_int,
    _read_table,
    _safe_path,
    _sha256,
    _table_similarity,
    compare_artifact,
    compare_artifacts,
    index_outputs,
    write_artifact_results,
)
from reproagent.config import ArtifactSpec
from reproagent.models import ArtifactComparison, OutputArtifact

# ---------------------------------------------------------------------------
# Environment budget parsing
# ---------------------------------------------------------------------------


def test_positive_env_int_uses_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIREPRO_TEST_LIMIT", raising=False)
    assert _positive_env_int("VERIREPRO_TEST_LIMIT", 42) == 42


def test_positive_env_int_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIREPRO_TEST_LIMIT", " 7 ")
    assert _positive_env_int("VERIREPRO_TEST_LIMIT", 1) == 7


def test_positive_env_int_rejects_malformed_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIREPRO_TEST_LIMIT", "not-a-number")
    with pytest.raises(ArtifactSecurityError, match="must be an integer"):
        _positive_env_int("VERIREPRO_TEST_LIMIT", 1)


@pytest.mark.parametrize("raw", ["0", "-3"])
def test_positive_env_int_rejects_non_positive_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VERIREPRO_TEST_LIMIT", raw)
    with pytest.raises(ArtifactSecurityError, match="must be positive"):
        _positive_env_int("VERIREPRO_TEST_LIMIT", 1)


def test_output_limits_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "VERIREPRO_MAX_OUTPUT_ENTRIES",
        "VERIREPRO_MAX_OUTPUT_FILES",
        "VERIREPRO_MAX_OUTPUT_FILE_BYTES",
        "VERIREPRO_MAX_TOTAL_OUTPUT_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)
    entries, files, file_bytes, total_bytes = _output_limits()
    assert (entries, files) == (8192, 4096)
    assert file_bytes == 1024 * 1024 * 1024
    assert total_bytes == 4 * 1024 * 1024 * 1024

    monkeypatch.setenv("VERIREPRO_MAX_OUTPUT_ENTRIES", "5")
    monkeypatch.setenv("VERIREPRO_MAX_OUTPUT_FILES", "6")
    monkeypatch.setenv("VERIREPRO_MAX_OUTPUT_FILE_BYTES", "7")
    monkeypatch.setenv("VERIREPRO_MAX_TOTAL_OUTPUT_BYTES", "8")
    assert _output_limits() == (5, 6, 7, 8)


# ---------------------------------------------------------------------------
# Safe path containment
# ---------------------------------------------------------------------------


def test_safe_path_resolves_nested_paths_inside_root(tmp_path: Path) -> None:
    resolved = _safe_path(tmp_path, "figures/sub/fig1.png")
    assert resolved == (tmp_path / "figures" / "sub" / "fig1.png").resolve()


def test_safe_path_rejects_parent_directory_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes allowed root"):
        _safe_path(tmp_path, "../outside.png")


def test_safe_path_rejects_deep_traversal_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes allowed root"):
        _safe_path(tmp_path, "a/b/../../../outside.png")


def test_safe_path_rejects_absolute_paths_outside_root(tmp_path: Path) -> None:
    external = tmp_path.parent / "elsewhere.dat"
    with pytest.raises(ValueError, match="escapes allowed root"):
        _safe_path(tmp_path, str(external))


def test_safe_path_accepts_absolute_path_equal_to_root(tmp_path: Path) -> None:
    assert _safe_path(tmp_path, str(tmp_path)) == tmp_path.resolve()


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def test_sha256_matches_reference_digest(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    payload = b"deterministic-payload-for-hashing"
    path.write_bytes(payload)
    assert _sha256(path) == hashlib.sha256(payload).hexdigest()


def test_sha256_distinguishes_tampered_content(tmp_path: Path) -> None:
    original = tmp_path / "original.bin"
    tampered = tmp_path / "tampered.bin"
    original.write_bytes(b"authentic experiment output")
    tampered.write_bytes(b"authentic experiment outpuT")
    assert _sha256(original) != _sha256(tampered)


# ---------------------------------------------------------------------------
# Output index building
# ---------------------------------------------------------------------------


def test_index_outputs_missing_directory_is_empty(tmp_path: Path) -> None:
    assert index_outputs(tmp_path / "does-not-exist") == ()


def test_index_outputs_empty_directory_is_empty(tmp_path: Path) -> None:
    assert index_outputs(tmp_path) == ()


def test_index_outputs_classifies_kinds_and_sorts_deterministically(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "b_plot.png").write_bytes(b"\x89PNG-data")
    (tmp_path / "a_data.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    (tmp_path / "c_notes.TXT").write_text("notes", encoding="utf-8")
    (tmp_path / "d_table.TSV").write_text("x\ty\n", encoding="utf-8")
    (tmp_path / "e_photo.JPG").write_bytes(b"jpeg-bytes")
    (tmp_path / "sub" / "nested.webp").write_bytes(b"webp")

    items = {item.path: item for item in index_outputs(tmp_path)}

    assert set(items) == {
        "a_data.csv",
        "b_plot.png",
        "c_notes.TXT",
        "d_table.TSV",
        "e_photo.JPG",
        "sub/nested.webp",
    }
    assert items["b_plot.png"].kind == "figure"
    assert items["e_photo.JPG"].kind == "figure"
    assert items["sub/nested.webp"].kind == "figure"
    assert items["a_data.csv"].kind == "table"
    assert items["d_table.TSV"].kind == "table"
    assert items["c_notes.TXT"].kind == "file"
    assert [item.path for item in index_outputs(tmp_path)] == sorted(
        item.path for item in index_outputs(tmp_path)
    )


def test_index_outputs_records_sizes_and_hashes(tmp_path: Path) -> None:
    payload = b"0123456789abcdef"
    path = tmp_path / "out.bin"
    path.write_bytes(payload)

    (artifact,) = index_outputs(tmp_path)

    assert artifact.path == "out.bin"
    assert artifact.size_bytes == len(payload)
    assert artifact.sha256 == hashlib.sha256(payload).hexdigest()


def test_index_outputs_detects_post_index_tampering(tmp_path: Path) -> None:
    path = tmp_path / "result.csv"
    path.write_text("accuracy\n0.9\n", encoding="utf-8")
    before = index_outputs(tmp_path)

    path.write_text("accuracy\n0.99\n", encoding="utf-8")
    after = index_outputs(tmp_path)

    assert before[0].sha256 != after[0].sha256
    assert after[0].size_bytes != before[0].size_bytes


def test_index_outputs_skips_symlinked_files_and_directories(tmp_path: Path) -> None:
    secret = tmp_path.parent / f"secret-{tmp_path.name}.txt"
    secret.write_text("outside data", encoding="utf-8")
    try:
        (tmp_path / "link.txt").symlink_to(secret)
        external_dir = tmp_path.parent / f"external-{tmp_path.name}"
        external_dir.mkdir(exist_ok=True)
        (external_dir / "leak.bin").write_bytes(b"leak")
        (tmp_path / "linked-dir").symlink_to(external_dir)
        (tmp_path / "broken.png").symlink_to(tmp_path / "never-created.png")
        (tmp_path / "real.txt").write_text("kept", encoding="utf-8")

        items = index_outputs(tmp_path)

        assert [item.path for item in items] == ["real.txt"]
    finally:
        secret.unlink(missing_ok=True)
        shutil.rmtree(external_dir, ignore_errors=True)


def test_index_outputs_rejects_symlinked_output_root(tmp_path: Path) -> None:
    real = tmp_path / "real-output"
    real.mkdir()
    link = tmp_path / "linked-output"
    link.symlink_to(real)
    with pytest.raises(ArtifactSecurityError, match="must not be a symbolic link"):
        index_outputs(link)


def test_index_outputs_enforces_entry_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERIREPRO_MAX_OUTPUT_ENTRIES", "1")
    (tmp_path / "one.txt").write_text("1", encoding="utf-8")
    (tmp_path / "two.txt").write_text("2", encoding="utf-8")
    with pytest.raises(ArtifactSecurityError, match="VERIREPRO_MAX_OUTPUT_ENTRIES"):
        index_outputs(tmp_path)


def test_index_outputs_enforces_file_count_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERIREPRO_MAX_OUTPUT_FILES", "1")
    (tmp_path / "one.txt").write_text("1", encoding="utf-8")
    (tmp_path / "two.txt").write_text("2", encoding="utf-8")
    with pytest.raises(ArtifactSecurityError, match="file-count limit 1"):
        index_outputs(tmp_path)


def test_index_outputs_enforces_per_file_byte_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERIREPRO_MAX_OUTPUT_FILE_BYTES", "4")
    (tmp_path / "big.bin").write_bytes(b"0123456789")
    with pytest.raises(ArtifactSecurityError, match="per-file limit 4 bytes"):
        index_outputs(tmp_path)


def test_index_outputs_enforces_cumulative_byte_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERIREPRO_MAX_TOTAL_OUTPUT_BYTES", "10")
    (tmp_path / "first.bin").write_bytes(b"x" * 8)
    (tmp_path / "second.bin").write_bytes(b"y" * 8)
    with pytest.raises(ArtifactSecurityError, match="cumulative read limit 10 bytes"):
        index_outputs(tmp_path)


# ---------------------------------------------------------------------------
# Compare guard
# ---------------------------------------------------------------------------


def test_guard_compare_file_rejects_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.png"
    target.write_bytes(b"data")
    link = tmp_path / "link.png"
    link.symlink_to(target)
    with pytest.raises(ArtifactSecurityError, match="must not be a symbolic link"):
        _guard_compare_file(link, label="reference figure")


def test_guard_compare_file_reports_unreadable_paths(tmp_path: Path) -> None:
    with pytest.raises(ArtifactSecurityError, match="could not stat reference figure"):
        _guard_compare_file(tmp_path / "missing.png", label="reference figure")


def test_guard_compare_file_enforces_explicit_limit(tmp_path: Path) -> None:
    path = tmp_path / "big.csv"
    path.write_bytes(b"0123456789")
    assert _guard_compare_file(path, label="reference table", limit=20) == 10
    with pytest.raises(ArtifactSecurityError, match="exceeds host comparison limit 4 bytes"):
        _guard_compare_file(path, label="reference table", limit=4)


def test_guard_compare_file_enforces_env_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERIREPRO_MAX_ARTIFACT_COMPARE_BYTES", "5")
    path = tmp_path / "model.bin"
    path.write_bytes(b"0123456789")
    with pytest.raises(ArtifactSecurityError, match="exceeds host comparison limit 5 bytes"):
        _guard_compare_file(path, label="reproduced file")


# ---------------------------------------------------------------------------
# Figure comparison
# ---------------------------------------------------------------------------


def _write_png(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (32, 24)) -> Path:
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


def test_identical_figures_score_perfect_similarity(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    output = tmp_path / "output"
    repository.mkdir()
    output.mkdir()
    payload = _write_png(repository / "fig.png", (120, 40, 200))
    (output / "fig.png").write_bytes(payload.read_bytes())
    spec = ArtifactSpec(name="fig", kind="figure", reference="fig.png", reproduced="fig.png")

    comparison = compare_artifact(spec, repository, output)

    assert comparison.score == pytest.approx(1.0)
    assert comparison.passed is True
    assert "normalized RGB similarity=1.0000" in comparison.detail
    assert "reference=32x24" in comparison.detail
    assert "reproduced=32x24" in comparison.detail


def test_inverted_figures_score_zero_similarity(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    output = tmp_path / "output"
    repository.mkdir()
    output.mkdir()
    _write_png(repository / "fig.png", (0, 0, 0))
    _write_png(output / "fig.png", (255, 255, 255))
    spec = ArtifactSpec(
        name="fig",
        kind="figure",
        reference="fig.png",
        reproduced="fig.png",
        threshold=0.95,
    )

    comparison = compare_artifact(spec, repository, output)

    assert comparison.score == 0.0
    assert comparison.passed is False
    assert "normalized RGB similarity=0.0000" in comparison.detail


def test_figure_similarity_enforces_pixel_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERIREPRO_MAX_IMAGE_PIXELS", "3")
    reference = _write_png(tmp_path / "ref.png", (0, 0, 0), size=(2, 2))
    reproduced = _write_png(tmp_path / "rep.png", (0, 0, 0), size=(2, 2))

    with pytest.raises(ArtifactSecurityError, match="reference figure exceeds host pixel limit"):
        _figure_similarity(reference, reproduced)


def test_figure_similarity_checks_reproduced_pixel_budget_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERIREPRO_MAX_IMAGE_PIXELS", "3")
    reference = _write_png(tmp_path / "ref.png", (0, 0, 0), size=(1, 1))
    reproduced = _write_png(tmp_path / "rep.png", (0, 0, 0), size=(4, 4))

    with pytest.raises(ArtifactSecurityError, match="reproduced figure exceeds host pixel limit"):
        _figure_similarity(reference, reproduced)


def test_compare_artifact_table_kind_applies_tolerances_end_to_end(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    output = tmp_path / "output"
    repository.mkdir()
    output.mkdir()
    (repository / "results.csv").write_text("accuracy\n100\n", encoding="utf-8")
    (output / "results.csv").write_text("accuracy\n100.5\n", encoding="utf-8")
    spec = ArtifactSpec(
        name="results",
        kind="table",
        reference="results.csv",
        reproduced="results.csv",
        threshold=0.95,
        absolute_tolerance=0.01,
        relative_tolerance=0.01,
    )

    comparison = compare_artifact(spec, repository, output)

    assert comparison.kind == "table"
    assert comparison.score == 1.0
    assert comparison.passed is True
    assert "cell agreement=2/2 (1.0000)" in comparison.detail


# ---------------------------------------------------------------------------
# Table comparison
# ---------------------------------------------------------------------------


def test_table_similarity_matches_numbers_within_tolerance(tmp_path: Path) -> None:
    reference = tmp_path / "ref.csv"
    reproduced = tmp_path / "rep.csv"
    reference.write_text("acc,loss\n100,-1.5\n", encoding="utf-8")
    reproduced.write_text("acc,loss\n100.9,-1.5000005\n", encoding="utf-8")

    score, detail = _table_similarity(
        reference,
        reproduced,
        absolute_tolerance=0.01,
        relative_tolerance=0.01,
    )

    assert score == 1.0
    assert "cell agreement=4/4 (1.0000)" in detail


def test_table_similarity_penalizes_ragged_and_diverging_cells(tmp_path: Path) -> None:
    reference = tmp_path / "ref.csv"
    reproduced = tmp_path / "rep.csv"
    reference.write_text("a,b\n1,2\n", encoding="utf-8")
    reproduced.write_text("a\n9\n", encoding="utf-8")

    score, detail = _table_similarity(
        reference,
        reproduced,
        absolute_tolerance=0.0,
        relative_tolerance=0.0,
    )

    assert score == 0.25
    assert "cell agreement=1/4 (0.2500)" in detail
    assert "reference_shape=2x2" in detail
    assert "reproduced_shape=2x1" in detail


def test_table_similarity_handles_whitespace_and_text_cells(tmp_path: Path) -> None:
    reference = tmp_path / "ref.csv"
    reproduced = tmp_path / "rep.csv"
    reference.write_text("label,value\nalpha,7\n", encoding="utf-8")
    reproduced.write_text('label,value\n" alpha ",7.00\n', encoding="utf-8")

    score, _detail = _table_similarity(
        reference,
        reproduced,
        absolute_tolerance=0.0,
        relative_tolerance=0.0,
    )

    assert score == 1.0


def test_table_similarity_of_two_empty_tables_is_perfect(tmp_path: Path) -> None:
    reference = tmp_path / "ref.csv"
    reproduced = tmp_path / "rep.csv"
    reference.write_text("", encoding="utf-8")
    reproduced.write_text("", encoding="utf-8")

    score, detail = _table_similarity(
        reference,
        reproduced,
        absolute_tolerance=0.0,
        relative_tolerance=0.0,
    )

    assert score == 1.0
    assert "cell agreement=0/0 (1.0000)" in detail


def test_read_table_uses_tab_delimiter_for_tsv(tmp_path: Path) -> None:
    path = tmp_path / "data.tsv"
    path.write_text("a\tb\n1\t2\n", encoding="utf-8")
    assert _read_table(path, label="reproduced") == [["a", "b"], ["1", "2"]]


def test_read_table_enforces_cell_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIREPRO_MAX_TABLE_CELLS", "3")
    path = tmp_path / "wide.csv"
    path.write_text("1,2,3,4\n", encoding="utf-8")
    with pytest.raises(ArtifactSecurityError, match="exceeds host cell limit 3"):
        _read_table(path, label="reference")


def test_read_table_enforces_byte_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIREPRO_MAX_TABLE_BYTES", "4")
    path = tmp_path / "big.csv"
    path.write_text("1,2,3,4,5,6\n", encoding="utf-8")
    with pytest.raises(ArtifactSecurityError, match="reference artifact exceeds"):
        _read_table(path, label="reference")


def test_read_table_wraps_csv_parser_errors(tmp_path: Path) -> None:
    path = tmp_path / "long-field.csv"
    path.write_text("header\n" + "y" * 512 + "\n", encoding="utf-8")
    original_limit = csv.field_size_limit()
    csv.field_size_limit(64)
    try:
        with pytest.raises(ArtifactSecurityError, match="could not parse reference table safely"):
            _read_table(path, label="reference")
    finally:
        csv.field_size_limit(original_limit)


# ---------------------------------------------------------------------------
# compare_artifact decisions
# ---------------------------------------------------------------------------


def test_compare_artifact_reports_missing_reference(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    output = tmp_path / "output"
    repository.mkdir()
    output.mkdir()
    (output / "result.png").write_bytes(b"something")
    spec = ArtifactSpec(
        name="figure-1",
        kind="figure",
        reference="missing.png",
        reproduced="result.png",
    )

    comparison = compare_artifact(spec, repository, output)

    assert comparison.score == 0.0
    assert comparison.passed is False
    assert comparison.detail == "reference artifact is missing"


def test_compare_artifact_reports_missing_reproduced(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    output = tmp_path / "output"
    repository.mkdir()
    output.mkdir()
    (repository / "expected.png").write_bytes(b"canonical")
    spec = ArtifactSpec(
        name="figure-1",
        kind="figure",
        reference="expected.png",
        reproduced="never-produced.png",
    )

    comparison = compare_artifact(spec, repository, output)

    assert comparison.score == 0.0
    assert comparison.passed is False
    assert comparison.detail == "reproduced artifact is missing"


def test_compare_artifact_file_kind_detects_tampering(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    output = tmp_path / "output"
    repository.mkdir()
    output.mkdir()
    authentic = b"experiment-log,v1,accuracy=0.9"
    (repository / "log.csv").write_bytes(authentic)

    honest = tmp_path / "honest"
    tampered = tmp_path / "tampered"
    honest.mkdir()
    tampered.mkdir()
    (honest / "log.csv").write_bytes(authentic)
    (tampered / "log.csv").write_bytes(authentic.replace(b"v1", b"v2"))

    spec = ArtifactSpec(name="log", kind="file", reference="log.csv", reproduced="log.csv")

    clean = compare_artifact(spec, repository, honest)
    manipulated = compare_artifact(spec, repository, tampered)

    assert clean.score == 1.0
    assert clean.detail == "SHA-256 match"
    assert clean.passed is True
    assert manipulated.score == 0.0
    assert manipulated.detail == "SHA-256 mismatch"
    assert manipulated.passed is False


def test_compare_artifact_normalizes_kind_case(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    output = tmp_path / "output"
    repository.mkdir()
    output.mkdir()
    payload = _write_png(repository / "fig.png", (10, 20, 30))
    (output / "fig.png").write_bytes(payload.read_bytes())
    spec = ArtifactSpec(name="fig", kind="FIGURE", reference="fig.png", reproduced="fig.png")

    comparison = compare_artifact(spec, repository, output)

    assert comparison.kind == "figure"
    assert comparison.score == pytest.approx(1.0)


def test_compare_artifact_rejects_unsupported_kind(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    output = tmp_path / "output"
    repository.mkdir()
    output.mkdir()
    (repository / "ref.wav").write_bytes(b"riff")
    (output / "rep.wav").write_bytes(b"riff")
    spec = ArtifactSpec(
        name="clip",
        kind="audio",
        reference="ref.wav",
        reproduced="rep.wav",
    )
    comparison = compare_artifact(spec, repository, output)
    assert comparison.score == 0.0
    assert comparison.passed is False
    assert comparison.detail == "unsupported artifact kind: audio"


def test_compare_artifact_contains_paths_within_roots(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    output = tmp_path / "output"
    repository.mkdir()
    output.mkdir()
    escaping = ArtifactSpec(
        name="escape",
        kind="file",
        reference="../outside.bin",
        reproduced="inside.bin",
    )
    with pytest.raises(ValueError, match="escapes allowed root"):
        compare_artifact(escaping, repository, output)


def test_compare_artifacts_preserves_spec_order(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    output = tmp_path / "output"
    repository.mkdir()
    output.mkdir()
    (repository / "only-ref.bin").write_bytes(b"ref")
    specs = (
        ArtifactSpec(name="first", kind="table", reference="nope.csv", reproduced="nope.csv"),
        ArtifactSpec(name="second", kind="file", reference="only-ref.bin", reproduced="absent.bin"),
    )

    comparisons = compare_artifacts(specs, repository, output)

    assert [item.name for item in comparisons] == ["first", "second"]
    assert all(item.passed is False for item in comparisons)


# ---------------------------------------------------------------------------
# Result index writing
# ---------------------------------------------------------------------------


def test_write_artifact_results_round_trip_and_layout(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "dir" / "artifact-results.json"
    comparison = ArtifactComparison(
        name="fig",
        kind="figure",
        reference="r.png",
        reproduced="p.png",
        score=0.987654321,
        threshold=0.95,
        passed=True,
        detail="normalized RGB similarity=0.9877",
    )
    output = OutputArtifact(
        path="figures/fig.png",
        kind="figure",
        size_bytes=1234,
        sha256="a" * 64,
    )

    written = write_artifact_results((comparison,), (output,), destination)

    assert written == destination
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert set(payload) == {"comparisons", "outputs"}
    assert payload["comparisons"][0]["name"] == "fig"
    assert payload["comparisons"][0]["score"] == pytest.approx(0.987654321)
    assert payload["outputs"][0] == {
        "path": "figures/fig.png",
        "kind": "figure",
        "size_bytes": 1234,
        "sha256": "a" * 64,
    }


def test_write_artifact_results_is_byte_deterministic(tmp_path: Path) -> None:
    comparison = ArtifactComparison(
        name="tbl",
        kind="table",
        reference="t.csv",
        reproduced="t.csv",
        score=1.0,
        threshold=0.95,
        passed=True,
        detail="cell agreement=4/4 (1.0000)",
    )
    first = write_artifact_results((comparison,), (), tmp_path / "run-a" / "index.json")
    second = write_artifact_results((comparison,), (), tmp_path / "run-b" / "index.json")

    assert first.read_bytes() == second.read_bytes()


def test_written_index_payload_validates_against_expected_schema(tmp_path: Path) -> None:
    comparison = ArtifactComparison(
        name="log",
        kind="file",
        reference="a.log",
        reproduced="a.log",
        score=0.0,
        threshold=1.0,
        passed=False,
        detail="SHA-256 mismatch",
    )
    destination = tmp_path / "artifact-results.json"
    write_artifact_results((comparison,), (), destination)

    raw = destination.read_text(encoding="utf-8")
    payload = json.loads(raw)
    required_comparison_keys = {
        "name",
        "kind",
        "reference",
        "reproduced",
        "score",
        "threshold",
        "passed",
        "detail",
    }
    assert set(payload["comparisons"][0]) == required_comparison_keys
    assert isinstance(payload["comparisons"][0]["passed"], bool)
    assert isinstance(payload["comparisons"][0]["score"], float)
    # A truncated/corrupted index must not silently validate as complete JSON.
    corrupted = destination.with_suffix(".corrupt.json")
    corrupted.write_text(raw[: len(raw) // 2], encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        json.loads(corrupted.read_text(encoding="utf-8"))


def test_table_similarity_can_compare_selected_scientific_columns(tmp_path: Path) -> None:
    reference = tmp_path / "paper.csv"
    reproduced = tmp_path / "run.csv"
    reference.write_text(
        "a1,a2,a3,meas_rank,meas_defect\n4,4,4,78,3\n",
        encoding="utf-8",
    )
    reproduced.write_text(
        "a1,a2,a3,src,tgt,meas_rank,pred_rank,meas_defect,pred_defect,match\n"
        "4,4,4,125,81,78,78,3,3,True\n",
        encoding="utf-8",
    )
    score, detail = _table_similarity(
        reference,
        reproduced,
        absolute_tolerance=0.0,
        relative_tolerance=0.0,
        columns=("a1", "a2", "a3", "meas_rank", "meas_defect"),
    )
    assert score == 1.0
    assert "selected_columns=a1,a2,a3,meas_rank,meas_defect" in detail


def test_table_similarity_selected_columns_fail_closed_when_ambiguous(tmp_path: Path) -> None:
    reference = tmp_path / "paper.csv"
    reproduced = tmp_path / "run.csv"
    reference.write_text("rank,rank\n78,78\n", encoding="utf-8")
    reproduced.write_text("rank\n78\n", encoding="utf-8")
    with pytest.raises(ArtifactSecurityError, match="exactly one column"):
        _table_similarity(
            reference,
            reproduced,
            absolute_tolerance=0.0,
            relative_tolerance=0.0,
            columns=("rank",),
        )
