from __future__ import annotations

import copy
import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

import reproagent.reprobench_adapter as adapter
from reproagent import __version__
from reproagent.config import ArtifactSpec
from reproagent.models import (
    ArtifactComparison,
    MetricComparison,
    OutputArtifact,
    ReproductionReport,
    StageResult,
)
from reproagent.reprobench_adapter import (
    ReproBenchContractError,
    ReproBenchTask,
    build_reprobench_result,
    load_reprobench_task,
    parse_reprobench_task,
    run_reprobench_task,
    write_reprobench_result,
)
from reproagent.reprobench_adapter import (
    build_parser as build_bench_parser,
)
from reproagent.reprobench_adapter import (
    main as adapter_main,
)
from reproagent.reprobench_summary import (
    ReproBenchSummaryError,
    summarize_reprobench_results,
    write_reprobench_summary,
)
from reproagent.reprobench_summary import (
    build_parser as build_summary_parser,
)
from reproagent.reprobench_summary import (
    main as summary_main,
)

_DELETE = object()


def make_report(**overrides: Any) -> ReproductionReport:
    values: dict[str, Any] = {
        "source": "2401.00001",
        "status": "PASS",
        "repository": "https://github.com/example/repo",
        "stacks": ("Python",),
        "stages": [
            StageResult("Paper resolved", "passed", "ok"),
            StageResult("Repository found", "passed", "ok"),
            StageResult("Environment built", "passed", "ok"),
            StageResult("Experiment executed", "passed", "ok"),
            StageResult("Outputs indexed", "passed", "ok"),
        ],
        "paper_metrics": {"accuracy": 0.9},
        "reproduced_metrics": {"accuracy": 0.91},
        "comparisons": [MetricComparison("accuracy", 0.9, 0.91, 0.01, 0.05, True)],
        "workspace": Path("ws"),
        "environment_plan": {
            "commit_sha": "a" * 40,
            "environment_fingerprint": "fp-1",
            "reproducibility_grade": "gold",
            "dependency_strategy": "requirements",
        },
        "artifact_comparisons": [],
        "output_artifacts": [OutputArtifact("results/metrics.json", "metrics", 128, "cd" * 32)],
    }
    values.update(overrides)
    return ReproductionReport(**values)


def make_task(**overrides: Any) -> ReproBenchTask:
    payload: dict[str, Any] = {
        "task_id": "case-0001",
        "domain": "machine-learning",
        "paper": "2401.00001",
        "expected_artifacts": ["results/metrics.json"],
    }
    payload.update(overrides)
    return parse_reprobench_task(payload)


def result_payload(
    report: ReproductionReport | None = None,
    task: ReproBenchTask | None = None,
    *,
    wall_clock_seconds: float = 1.5,
    execution_requested: bool = True,
    operator_interventions: tuple[str, ...] = (),
    model_usage: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    return build_reprobench_result(
        task if task is not None else make_task(),
        report if report is not None else make_report(),
        wall_clock_seconds=wall_clock_seconds,
        execution_requested=execution_requested,
        operator_interventions=operator_interventions,
        model_usage=model_usage,
    ).to_dict()


def write_payload(path: Path, name: str, payload: dict[str, Any]) -> Path:
    target = path / name
    target.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return target


def mutated(base: dict[str, Any], dotted_path: str, value: Any) -> dict[str, Any]:
    clone = copy.deepcopy(base)
    keys = dotted_path.split(".")
    node: Any = clone
    for key in keys[:-1]:
        node = node[key]
    if value is _DELETE:
        del node[keys[-1]]
    else:
        node[keys[-1]] = value
    return clone


def failing_metric_report(**overrides: Any) -> ReproductionReport:
    overrides.setdefault("comparisons", [MetricComparison("accuracy", 0.9, 0.4, 0.5, 0.05, False)])
    return make_report(status="FAIL", **overrides)


def partial_report() -> ReproductionReport:
    return make_report(status="PARTIAL", comparisons=[], reproduced_metrics={})


USAGE_FULL: tuple[dict[str, Any], ...] = (
    {
        "cost_usd": 0.25,
        "request_count": 1,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "cached_tokens": 2,
        "reasoning_tokens": 3,
        "duration_seconds": 1.25,
    },
)


def test_parse_task_minimal_shape_and_defaults() -> None:
    task = parse_reprobench_task(
        {
            "task_id": "case-1",
            "domain": "ml",
            "paper": "https://example.com/paper.pdf",
            "expected_artifacts": [],
        }
    )
    assert task.schema_version == 1
    assert task.extra_fields == ()
    assert task.to_dict() == {
        "schema_version": 1,
        "task_id": "case-1",
        "domain": "ml",
        "paper": "https://example.com/paper.pdf",
        "expected_artifacts": [],
        "extra_fields": [],
    }


@pytest.mark.parametrize(
    ("paper", "expected"),
    [
        ("2401.12345", "2401.12345"),
        ("2401.12345v3", "2401.12345v3"),
        ("arxiv:2401.12345", "arxiv:2401.12345"),
        ("doi:10.1234/journal.article", "doi:10.1234/journal.article"),
        ("10.9999/short", "10.9999/short"),
        ("https://example.org/paper.pdf", "https://example.org/paper.pdf"),
    ],
)
def test_parse_task_accepts_supported_paper_sources(paper: str, expected: str) -> None:
    task = make_task(paper=paper)
    assert task.paper == expected


def test_parse_task_strips_dot_prefix_from_artifacts_and_sorts_extra_fields() -> None:
    task = make_task(
        expected_artifacts=["./results/metrics.json", ".\\sub\\table.csv"],
        zeta=1,
        alpha=2,
    )
    assert task.expected_artifacts == ("results/metrics.json", "sub/table.csv")
    assert task.extra_fields == ("alpha", "zeta")


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"schema_version": 2}, "unsupported ReproBench task schema_version"),
        ({"schema_version": "1"}, "unsupported ReproBench task schema_version"),
        ({"task_id": None}, "task_id must be a string"),
        ({"task_id": ""}, "task_id must not be empty"),
        ({"task_id": "   "}, "task_id must not be empty"),
        ({"task_id": "-leading"}, "task_id must start"),
        ({"task_id": "has space"}, "task_id must start"),
        ({"task_id": "x" * 201}, "task_id exceeds 200 characters"),
        ({"task_id": "ok\x00id"}, "task_id contains a NUL byte"),
        ({"domain": 3}, "domain must be a string"),
        ({"domain": ""}, "domain must not be empty"),
        ({"paper": None}, "paper must be a string"),
        ({"paper": ""}, "paper must not be empty"),
        ({"paper": "/local/paper.pdf"}, "credential-free HTTPS URL"),
        ({"paper": "file:///etc/passwd"}, "credential-free HTTPS URL"),
        ({"paper": "http://example.com/paper.pdf"}, "credential-free HTTPS URL"),
        ({"paper": "https://user@example.com/paper.pdf"}, "credential-free HTTPS URL"),
        ({"paper": "https://user:pw@example.com/x"}, "credential-free HTTPS URL"),
        ({"paper": "https://example.com/x?download=1"}, "credential-free HTTPS URL"),
        ({"paper": "https://example.com/x#fragment"}, "credential-free HTTPS URL"),
        ({"expected_artifacts": "metrics.json"}, "expected_artifacts must be a list of strings"),
        ({"expected_artifacts": [1]}, "expected_artifacts[0] must be a string"),
        ({"expected_artifacts": [""]}, "expected_artifacts[0] must not be empty"),
        ({"expected_artifacts": ["/abs/x.json"]}, "must be a relative artifact"),
        ({"expected_artifacts": ["../escape.json"]}, "must be a relative artifact"),
        ({"expected_artifacts": ["a/../b.json"]}, "must be a relative artifact"),
        ({"expected_artifacts": ["dir/"]}, "must be a relative artifact"),
        ({"expected_artifacts": ["C:/data.csv"]}, "must be a relative artifact"),
        ({"expected_artifacts": ["."]}, "must be a relative artifact"),
    ],
)
def test_parse_task_contract_rejections(overrides: dict[str, Any], fragment: str) -> None:
    payload: dict[str, Any] = {
        "task_id": "case-0001",
        "domain": "ml",
        "paper": "2401.00001",
        "expected_artifacts": [],
    }
    payload.update(overrides)
    with pytest.raises(ReproBenchContractError, match=re.escape(fragment)):
        parse_reprobench_task(payload)


def test_parse_task_rejects_duplicate_and_oversized_artifact_lists() -> None:
    with pytest.raises(ReproBenchContractError, match="must not contain duplicates"):
        make_task(expected_artifacts=["a.json", "a.json"])
    with pytest.raises(ReproBenchContractError, match="at most 128 entries"):
        make_task(expected_artifacts=[f"f{i}.json" for i in range(129)])


@pytest.mark.parametrize(
    "extras",
    [
        {f"field{i:02d}": i for i in range(65)},
        {"padded ": 1},
        {" padded": 1},
        {"ctl\x01name": 1},
        {"x" * 101: 1},
        {"": 1},
    ],
)
def test_parse_task_rejects_unbounded_or_unprintable_extra_fields(extras: dict) -> None:
    payload: dict[str, Any] = {
        "task_id": "case-0001",
        "domain": "ml",
        "paper": "2401.00001",
        "expected_artifacts": [],
    }
    payload.update(extras)
    with pytest.raises(ReproBenchContractError, match="unknown field"):
        parse_reprobench_task(payload)


def test_parse_task_accepts_sixty_four_extra_fields() -> None:
    task = make_task(**{f"k{i:02d}": i for i in range(64)})
    assert len(task.extra_fields) == 64


def test_parse_task_rejects_non_object_payload() -> None:
    with pytest.raises(ReproBenchContractError, match="must contain an object"):
        parse_reprobench_task(["not", "an", "object"])


def test_load_task_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "task.json"
    path.write_text(
        json.dumps(
            {
                "task_id": "case-0001",
                "domain": "ml",
                "paper": "2401.00001",
                "expected_artifacts": ["./results/metrics.json"],
                "note": "hello",
            }
        ),
        encoding="utf-8",
    )
    task = load_reprobench_task(path)
    assert task.expected_artifacts == ("results/metrics.json",)
    assert task.extra_fields == ("note",)


def test_load_task_rejects_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(ReproBenchContractError, match="must not be a symlink"):
        load_reprobench_task(link)


def test_load_task_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ReproBenchContractError, match="could not read benchmark task"):
        load_reprobench_task(tmp_path / "missing.json")


def test_load_task_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(ReproBenchContractError, match="regular JSON file"):
        load_reprobench_task(tmp_path)


def test_load_task_rejects_invalid_utf8_and_json(tmp_path: Path) -> None:
    bad_bytes = tmp_path / "bytes.json"
    bad_bytes.write_bytes(b"\xff\xfe\x00broken")
    with pytest.raises(ReproBenchContractError, match="invalid benchmark task JSON"):
        load_reprobench_task(bad_bytes)
    bad_json = tmp_path / "syntax.json"
    bad_json.write_text("{oops", encoding="utf-8")
    with pytest.raises(ReproBenchContractError, match="invalid benchmark task JSON"):
        load_reprobench_task(bad_json)


def test_load_task_rejects_non_finite_constants(tmp_path: Path) -> None:
    path = tmp_path / "nan.json"
    path.write_text('{"task_id": "a1", "weight": NaN}', encoding="utf-8")
    with pytest.raises(ReproBenchContractError, match="non-finite JSON number"):
        load_reprobench_task(path)


def test_load_task_enforces_host_size_limit(tmp_path: Path) -> None:
    path = tmp_path / "huge.json"
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ReproBenchContractError, match="byte host limit"):
        load_reprobench_task(path)


def test_build_result_success_measurements_are_grounded() -> None:
    payload = result_payload(wall_clock_seconds=2.75)
    assert payload["outcome"] == "success"
    assert payload["failure_taxonomy"] == []
    assert payload["benchmark"] == "reprobench"
    assert payload["agent"] == {
        "name": "VeriRepro",
        "version": __version__,
        "report_schema_version": 1,
    }
    m = payload["measurements"]
    assert m["verirepro_status"] == "PASS"
    assert m["environment_build_status"] == "passed"
    assert m["experiment_execution_status"] == "passed"
    assert m["experiment_execution_success"] is True
    assert m["grounded_metric_pass_rate"] == 1.0
    assert m["artifact_comparison_pass_rate"] is None
    assert m["expected_artifact_rate"] == 1.0
    assert m["expected_artifacts_found"] == ["results/metrics.json"]
    assert m["expected_artifacts_missing"] == []
    assert m["environment_plan_success"] is True
    assert m["repository_commit"] == "a" * 40
    assert m["environment_fingerprint"] == "fp-1"
    assert m["environment_reproducibility_grade"] == "gold"
    assert m["dependency_strategy"] == "requirements"
    assert m["model_cost_usd"] is None
    assert m["token_usage"] is None
    assert payload["wall_clock_seconds"] == 2.75
    assert [stage["name"] for stage in payload["stages"]] == [
        "Paper resolved",
        "Repository found",
        "Environment built",
        "Experiment executed",
        "Outputs indexed",
    ]


def test_build_result_clamps_negative_wall_clock_to_zero() -> None:
    payload = result_payload(wall_clock_seconds=-5.0)
    assert payload["wall_clock_seconds"] == 0.0


def test_build_result_partial_declares_only_soft_taxonomy() -> None:
    payload = result_payload(report=partial_report())
    assert payload["outcome"] == "partial"
    assert payload["failure_taxonomy"] == ["insufficient_evidence_or_execution"]
    m = payload["measurements"]
    assert m["grounded_metric_comparisons"] == 0
    assert m["grounded_metric_passed"] == 0
    assert m["grounded_metric_pass_rate"] is None


def test_build_result_fail_without_other_signals_keeps_specific_cause() -> None:
    payload = result_payload(report=failing_metric_report())
    assert payload["outcome"] == "failure"
    assert payload["failure_taxonomy"] == ["grounded_metric_mismatch"]
    assert payload["measurements"]["grounded_metric_pass_rate"] == 0.0


def test_build_result_unclassified_fail_fallback_when_no_signal_matches() -> None:
    report = make_report(
        status="FAIL",
        stages=[
            StageResult("Paper resolved", "passed", "ok"),
            StageResult("Repository found", "passed", "ok"),
            StageResult("Experiment executed", "passed", "ok"),
        ],
        comparisons=[],
        reproduced_metrics={},
        output_artifacts=[],
    )
    payload = result_payload(
        task=make_task(expected_artifacts=[]),
        report=report,
    )
    assert payload["failure_taxonomy"] == ["unclassified_verirepro_failure"]
    assert payload["outcome"] == "failure"


def test_build_result_taxonomy_covers_failed_stages_and_artifacts_in_order() -> None:
    report = make_report(
        status="FAIL",
        stages=[
            StageResult("Datasets downloaded", "failed", "offline"),
            StageResult("Environment built", "failed", "pip broken"),
        ],
        artifact_comparisons=[
            ArtifactComparison("fig1", "image", "ref", "rep", 0.1, 0.9, False, "dissimilar")
        ],
    )
    payload = result_payload(report=report)
    assert payload["failure_taxonomy"] == [
        "dataset_materialization_failure",
        "environment_build_failure",
        "artifact_comparison_mismatch",
    ]


def test_build_result_partial_with_hard_stage_failure_upgrades_outcome() -> None:
    report = make_report(
        status="PARTIAL",
        comparisons=[],
        reproduced_metrics={},
        stages=[
            StageResult("Environment built", "failed", "solver conflict"),
            StageResult("Experiment executed", "skipped", "not attempted"),
        ],
    )
    payload = result_payload(report=report)
    assert payload["outcome"] == "failure"
    assert payload["failure_taxonomy"] == ["environment_build_failure"]
    assert payload["measurements"]["experiment_execution_success"] is None


def test_build_result_missing_expected_artifact_downgrades_pass_to_failure() -> None:
    report = make_report(output_artifacts=[])
    payload = result_payload(report=report)
    assert payload["outcome"] == "failure"
    assert payload["failure_taxonomy"] == ["expected_artifact_missing"]
    m = payload["measurements"]
    assert m["expected_artifacts_found"] == []
    assert m["expected_artifacts_missing"] == ["results/metrics.json"]
    assert m["expected_artifact_rate"] == 0.0


def test_build_result_artifact_matching_rules() -> None:
    flat = make_task(expected_artifacts=["metrics.json"])
    payload = result_payload(
        task=flat,
        report=make_report(
            output_artifacts=[OutputArtifact("deeply/nested/out/metrics.json", "metrics", 1, "aa")]
        ),
    )
    assert payload["measurements"]["expected_artifacts_found"] == ["metrics.json"]

    strict = make_task(expected_artifacts=["results/metrics.json"])
    payload = result_payload(
        task=strict,
        report=make_report(
            output_artifacts=[OutputArtifact("other/results/metrics.json", "metrics", 1, "bb")]
        ),
    )
    assert payload["measurements"]["expected_artifacts_missing"] == ["results/metrics.json"]

    dotted = make_task(expected_artifacts=["./results/metrics.json"])
    payload = result_payload(task=dotted)
    assert payload["measurements"]["expected_artifact_rate"] == 1.0


def test_build_result_aggregates_model_usage_into_measurements() -> None:
    payload = result_payload(model_usage=USAGE_FULL)
    m = payload["measurements"]
    assert m["model_cost_usd"] == 0.25
    assert m["token_usage"]["calls_with_telemetry"] == 1
    assert m["token_usage"]["total_tokens"] == 15
    assert m["token_usage"]["duration_seconds"] == 1.25


def test_write_result_creates_parents_and_is_byte_deterministic(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "dir" / "result.json"
    result = build_reprobench_result(
        make_task(),
        make_report(),
        wall_clock_seconds=1.0,
        execution_requested=True,
        operator_interventions=("command_override",),
    )
    written = write_reprobench_result(result, destination)
    assert written == destination
    expected = json.dumps(result.to_dict(), indent=2, allow_nan=False) + "\n"
    assert destination.read_text(encoding="utf-8") == expected
    assert destination.read_text(encoding="utf-8").endswith("}\n")


def test_run_task_forwards_all_options_and_counts_interventions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_reproduce(source: str, **kwargs: Any) -> ReproductionReport:
        seen["source"] = source
        seen.update(kwargs)
        return partial_report()

    monkeypatch.setattr(adapter, "reproduce", fake_reproduce)
    result = run_reprobench_task(
        make_task(),
        workspace_root=tmp_path,
        execute=False,
        repository_url="https://github.com/operator/fork",
        repository_ref="v2",
        command="python train.py",
        python_version="3.12",
        timeout=60,
        use_llm=False,
        llm_model="test-model",
        allow_network=True,
        trust_repository_contract=True,
    )
    assert seen["source"] == "2401.00001"
    assert seen["workspace_root"] == tmp_path
    assert seen["execute"] is False
    assert seen["repository_url"] == "https://github.com/operator/fork"
    assert seen["repository_ref"] == "v2"
    assert seen["command"] == "python train.py"
    assert seen["python_version"] == "3.12"
    assert seen["timeout"] == 60
    assert seen["use_llm"] is False
    assert seen["llm_model"] == "test-model"
    assert seen["allow_network"] is True
    assert seen["trust_repository_contract"] is True
    assert result.outcome == "partial"
    assert result.execution_requested is False
    assert result.operator_interventions == (
        "repository_override",
        "repository_ref_override",
        "command_override",
        "network_authorization",
        "scientific_contract_authorization",
    )


def test_run_task_records_host_scientific_artifact_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_reproduce(source: str, **kwargs: Any) -> ReproductionReport:
        seen.update(kwargs)
        return partial_report()

    monkeypatch.setattr(adapter, "reproduce", fake_reproduce)
    reference_root = tmp_path / "references"
    reference_root.mkdir()
    spec = ArtifactSpec(
        name="paper-table",
        kind="table",
        reference="paper.csv",
        reproduced="run.csv",
    )
    result = run_reprobench_task(
        make_task(expected_artifacts=[]),
        workspace_root=tmp_path,
        trusted_artifact_contract=(spec,),
        trusted_reference_root=reference_root,
    )
    assert seen["trusted_artifact_contract"] == (spec,)
    assert seen["trusted_reference_root"] == reference_root
    assert "host_scientific_artifact_contract" in result.operator_interventions


def test_run_task_without_overrides_has_zero_interventions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "reproduce", lambda source, **kwargs: make_report())
    result = run_reprobench_task(make_task(), workspace_root=Path("."))
    assert result.outcome == "success"
    assert result.operator_interventions == ()
    assert result.to_dict()["intervention_count"] == 0


@contextmanager
def _fake_model_capture():
    yield [
        {
            "cost_usd": 1.25,
            "request_count": 2,
            "prompt_tokens": 30,
            "completion_tokens": 12,
            "total_tokens": 42,
            "duration_seconds": 2.5,
        }
    ]


def test_run_task_captures_model_usage_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "reproduce", lambda source, **kwargs: make_report())
    monkeypatch.setattr(adapter, "capture_model_usage", _fake_model_capture)
    result = run_reprobench_task(make_task(), workspace_root=Path("."))
    assert result.to_dict()["measurements"]["model_cost_usd"] == 1.25
    assert result.to_dict()["measurements"]["token_usage"]["total_tokens"] == 42


@pytest.mark.parametrize(
    ("status", "report_factory", "expected_rc", "expected_outcome"),
    [
        ("PASS", make_report, 0, "success"),
        ("PARTIAL", partial_report, 2, "partial"),
        ("FAIL", failing_metric_report, 1, "failure"),
    ],
)
def test_adapter_main_exit_codes_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    report_factory: Any,
    expected_rc: int,
    expected_outcome: str,
) -> None:
    monkeypatch.setattr(adapter, "reproduce", lambda source, **kwargs: report_factory())
    task_path = tmp_path / "task.json"
    task_path.write_text(
        json.dumps(
            {
                "task_id": "case-0001",
                "domain": "ml",
                "paper": "2401.00001",
                "expected_artifacts": ["results/metrics.json"],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "out" / "result.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verirepro-reprobench",
            str(task_path),
            "--output",
            str(output),
        ],
    )
    assert adapter_main() == expected_rc
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["outcome"] == expected_outcome
    stdout = capsys.readouterr().out
    assert f"ReproBench task case-0001: outcome={expected_outcome}" in stdout
    assert f"status={status}" in stdout
    assert str(output) in stdout


def test_adapter_main_forwards_cli_flags_to_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_reproduce(source: str, **kwargs: Any) -> ReproductionReport:
        seen.update(kwargs)
        seen["source"] = source
        return make_report()

    monkeypatch.setattr(adapter, "reproduce", fake_reproduce)
    task_path = write_payload(
        tmp_path,
        "task.json",
        {
            "task_id": "case-0001",
            "domain": "ml",
            "paper": "2401.00001",
            "expected_artifacts": [],
        },
    )
    workspace = tmp_path / "ws"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verirepro-reprobench",
            str(task_path),
            "--workspace",
            str(workspace),
            "--no-execute",
            "--no-llm",
            "--repo",
            "https://github.com/operator/fork",
            "--ref",
            "v2",
            "--command",
            "python run.py",
            "--python",
            "3.12",
            "--timeout",
            "77",
            "--allow-network",
            "--trust-repository-contract",
        ],
    )
    assert adapter_main() == 0
    assert seen["execute"] is False
    assert seen["use_llm"] is False
    assert seen["llm_model"] is None
    assert seen["workspace_root"] == workspace
    assert seen["timeout"] == 77
    assert seen["trust_repository_contract"] is True


def test_adapter_main_propagates_contract_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_path = tmp_path / "bad.json"
    task_path.write_text(
        '{"task_id": "-bad", "domain": "ml", "paper": "2401.00001", "expected_artifacts": []}',
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["verirepro-reprobench", str(task_path)])
    with pytest.raises(ReproBenchContractError, match="task_id must start"):
        adapter_main()


def test_adapter_cli_rejects_missing_arguments_bad_types_unknown_flags() -> None:
    with pytest.raises(SystemExit) as missing:
        build_bench_parser().parse_args([])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as bad_type:
        build_bench_parser().parse_args(["task.json", "--timeout", "soon"])
    assert bad_type.value.code == 2
    with pytest.raises(SystemExit) as unknown_flag:
        build_bench_parser().parse_args(["task.json", "--max-cases", "5"])
    assert unknown_flag.value.code == 2


def test_summary_requires_at_least_one_result() -> None:
    with pytest.raises(ReproBenchSummaryError, match="at least one ReproBench result"):
        summarize_reprobench_results([])
    with pytest.raises(SystemExit) as exc:
        build_summary_parser().parse_args([])
    assert exc.value.code == 2


def test_summary_single_success_key_fields(tmp_path: Path) -> None:
    path = write_payload(tmp_path, "only-result.json", result_payload(model_usage=USAGE_FULL))
    payload = summarize_reprobench_results([path])
    assert payload["schema_version"] == 1
    assert payload["benchmark"] == "reprobench"
    assert payload["result_schema_version"] == 1
    s = payload["summary"]
    assert s["cases"] == 1
    assert s["outcomes"] == {"success": 1}
    assert s["success_rate"] == 1.0
    assert s["partial_rate"] == 0.0
    assert s["failure_rate"] == 0.0
    assert s["zero_intervention_cases"] == 1
    assert s["zero_intervention_rate"] == 1.0
    assert s["interventions_total"] == 0
    assert s["agents"] == {f"VeriRepro@{__version__}": 1}
    assert s["failure_taxonomy"] == {}
    assert s["domains"] == {
        "machine-learning": {
            "cases": 1,
            "outcomes": {"success": 1},
            "success_rate": 1.0,
        }
    }
    assert len(payload["inputs"]) == 1
    record = payload["inputs"][0]
    assert record["file"] == "only-result.json"
    assert record["task_id"] == "case-0001"
    assert len(record["sha256"]) == 64


def test_summary_mixed_outcomes_totals_and_determinism(tmp_path: Path) -> None:
    success = write_payload(
        tmp_path,
        "b-success.json",
        result_payload(
            operator_interventions=("command_override", "network_authorization"),
            wall_clock_seconds=0.5,
        ),
    )
    partial = write_payload(
        tmp_path,
        "c-partial.json",
        result_payload(
            task=make_task(task_id="case-0002", domain="vision"),
            report=partial_report(),
            wall_clock_seconds=1.0,
        ),
    )
    failure = write_payload(
        tmp_path,
        "a-failure.json",
        result_payload(
            task=make_task(task_id="case-0003"),
            report=failing_metric_report(),
            wall_clock_seconds=1.5,
        ),
    )
    first = summarize_reprobench_results([success, partial, failure])
    s = first["summary"]
    assert s["cases"] == 3
    assert s["outcomes"] == {"failure": 1, "partial": 1, "success": 1}
    assert s["success_rate"] == pytest.approx(1 / 3)
    assert s["partial_rate"] == pytest.approx(1 / 3)
    assert s["failure_rate"] == pytest.approx(1 / 3)
    assert s["zero_intervention_cases"] == 2
    assert s["interventions_total"] == 2
    assert s["wall_clock_seconds_total"] == 3.0
    assert s["wall_clock_seconds_mean"] == 1.0
    assert s["wall_clock_seconds_median"] == 1.0
    assert s["failure_taxonomy"] == {
        "grounded_metric_mismatch": 1,
        "insufficient_evidence_or_execution": 1,
    }
    assert s["domains"] == {
        "machine-learning": {
            "cases": 2,
            "outcomes": {"failure": 1, "success": 1},
            "success_rate": 0.5,
        },
        "vision": {"cases": 1, "outcomes": {"partial": 1}, "success_rate": 0.0},
    }
    assert [item["file"] for item in first["inputs"]] == [
        "a-failure.json",
        "b-success.json",
        "c-partial.json",
    ]

    rerun = summarize_reprobench_results([str(failure), str(success), str(partial)])
    assert json.dumps(rerun, indent=2) == json.dumps(first, indent=2)


def test_summary_never_counts_unknown_stage_as_passed(tmp_path: Path) -> None:
    executed = write_payload(tmp_path, "executed.json", result_payload())
    skipped = write_payload(
        tmp_path,
        "skipped.json",
        result_payload(
            task=make_task(task_id="case-0002"),
            report=make_report(
                status="PARTIAL",
                comparisons=[],
                reproduced_metrics={},
                stages=[
                    StageResult("Paper resolved", "passed", "ok"),
                    StageResult("Repository found", "passed", "ok"),
                ],
            ),
        ),
    )
    s = summarize_reprobench_results([executed, skipped])["summary"]
    assert s["experiment_execution"]["statuses"] == {"passed": 1}
    assert s["experiment_execution"]["attempted"] == 1
    assert s["experiment_execution"]["passed"] == 1
    assert s["experiment_execution"]["pass_rate"] == 1.0
    assert s["environment_build"]["attempted"] == 1
    assert s["environment_build"]["statuses"] == {"passed": 1}


def test_summary_comparison_and_artifact_totals(tmp_path: Path) -> None:
    first = write_payload(tmp_path, "r1.json", result_payload())
    second = write_payload(
        tmp_path,
        "r2.json",
        result_payload(
            task=make_task(task_id="case-0002"),
            report=failing_metric_report(
                comparisons=[
                    MetricComparison("accuracy", 0.9, 0.95, 0.05, 0.05, True),
                    MetricComparison("f1", 0.8, 0.2, 0.6, 0.05, False),
                ],
                artifact_comparisons=[
                    ArtifactComparison("fig", "image", "ref", "rep", 0.99, 0.9, True, "ok")
                ],
            ),
        ),
    )
    s = summarize_reprobench_results([first, second])["summary"]
    assert s["grounded_metrics"] == {
        "tasks_with_comparisons": 2,
        "comparisons": 3,
        "passed": 2,
        "pass_rate": pytest.approx(2 / 3),
    }
    assert s["artifact_comparisons"]["tasks_with_comparisons"] == 1
    assert s["artifact_comparisons"]["pass_rate"] == 1.0

    null_comparisons = mutated(
        result_payload(task=make_task(task_id="case-0003")),
        "measurements.grounded_metric_passed",
        None,
    )
    null_comparisons = mutated(null_comparisons, "measurements.grounded_metric_comparisons", None)
    no_expectations = mutated(
        result_payload(task=make_task(task_id="case-0004")),
        "measurements.expected_artifacts",
        None,
    )
    no_expectations = mutated(no_expectations, "measurements.expected_artifacts_found", None)
    no_expectations = mutated(no_expectations, "measurements.expected_artifacts_missing", None)
    sparse = write_payload(tmp_path, "r3.json", null_comparisons)
    sparse_two = write_payload(tmp_path, "r4.json", no_expectations)
    extended = summarize_reprobench_results([first, second, sparse, sparse_two])["summary"]
    assert extended["grounded_metrics"]["comparisons"] == 4
    assert extended["grounded_metrics"]["passed"] == 3
    assert extended["grounded_metrics"]["tasks_with_comparisons"] == 3
    assert extended["expected_artifacts"]["expected"] == 3
    assert extended["expected_artifacts"]["found_rate"] == 1.0
    assert s["expected_artifacts"] == {
        "tasks_with_expectations": 2,
        "expected": 2,
        "found": 2,
        "found_rate": 1.0,
    }


def test_summary_model_usage_totals(tmp_path: Path) -> None:
    first = write_payload(tmp_path, "r1.json", result_payload(model_usage=USAGE_FULL))
    second = write_payload(
        tmp_path,
        "r2.json",
        result_payload(
            task=make_task(task_id="case-0002"),
            model_usage=(
                {
                    "cost_usd": 0.5,
                    "request_count": 2,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                    "cached_tokens": None,
                    "reasoning_tokens": None,
                    "duration_seconds": 0.75,
                },
            ),
        ),
    )
    usage = summarize_reprobench_results([first, second])["summary"]["model_usage"]
    assert usage["cases_with_cost"] == 2
    assert usage["cost_usd_total"] == 0.75
    assert usage["cases_with_token_usage"] == 2
    assert usage["calls_with_telemetry"] == 2
    assert usage["request_count"] == 3
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 5
    assert usage["total_tokens"] == 15
    assert usage["cached_tokens"] == 2
    assert usage["reasoning_tokens"] == 3
    assert usage["duration_seconds"] == 2.0


def test_summary_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    first = write_payload(tmp_path, "one.json", result_payload())
    second = write_payload(tmp_path, "two.json", result_payload())
    with pytest.raises(ReproBenchSummaryError, match="duplicate benchmark task_id"):
        summarize_reprobench_results([first, second])


BASE_PAYLOAD = result_payload(model_usage=USAGE_FULL)


@pytest.mark.parametrize(
    ("dotted_path", "value", "fragment"),
    [
        ("schema_version", 99, "unsupported result schema_version"),
        ("schema_version", _DELETE, "unsupported result schema_version"),
        ("benchmark", "other", "benchmark must be 'reprobench'"),
        ("outcome", "UNKNOWN", "invalid outcome"),
        ("outcome", "pass", "invalid outcome"),
        ("outcome", _DELETE, "invalid outcome"),
        ("task", {}, "unsupported task schema_version"),
        ("task", "nope", "result task must be an object"),
        ("task.schema_version", 2, "unsupported task schema_version"),
        ("task.task_id", "", "task_id is missing"),
        ("task.task_id", "  ", "task_id is missing"),
        ("task.domain", "", "domain is missing"),
        ("wall_clock_seconds", -0.5, "wall_clock_seconds must be >= 0.0"),
        ("wall_clock_seconds", "fast", "wall_clock_seconds must be numeric"),
        ("execution_requested", 1, "execution_requested must be boolean"),
        ("operator_interventions", ["net", "net"], "must not contain duplicates"),
        ("operator_interventions", [""], "list of non-empty strings"),
        ("operator_interventions", "net", "list of non-empty strings"),
        ("intervention_count", 7, "intervention_count must equal"),
        ("intervention_count", _DELETE, "intervention_count must be a non-negative"),
        ("intervention_count", -1, "intervention_count must be a non-negative"),
        ("measurements", _DELETE, "measurements must be an object"),
        ("measurements", [], "measurements must be an object"),
        ("measurements.grounded_metric_passed", 5, "grounded_metric_passed cannot exceed"),
        ("measurements.grounded_metric_comparisons", None, "or both be null"),
        (
            "measurements.artifact_comparisons_passed",
            3,
            "artifact_comparisons_passed cannot exceed",
        ),
        ("measurements.experiment_execution_status", "running", "invalid stage status values"),
        ("measurements.expected_artifacts_found", ["ghost.json"], "exactly partition"),
        (
            "measurements.expected_artifacts_missing",
            ["results/metrics.json"],
            "both found and missing",
        ),
        ("measurements.model_cost_usd", -1.0, "model_cost_usd must be >= 0.0"),
        ("measurements.model_cost_usd", "cheap", "model_cost_usd must be numeric"),
        ("measurements.token_usage", [], "token_usage must be an object or null"),
        (
            "measurements.token_usage.prompt_tokens",
            -1,
            "prompt_tokens must be a non-negative integer",
        ),
        (
            "measurements.token_usage.total_tokens",
            "many",
            "total_tokens must be a non-negative integer",
        ),
        ("measurements.token_usage.duration_seconds", -1.0, "duration_seconds must be >= 0.0"),
        ("stages", [{"name": "S", "status": "running"}], "stage status is invalid"),
        ("stages", [{"name": "S"}], "only name/status fields"),
        ("stages", [{"name": "", "status": "passed"}], "stage name is invalid"),
        ("stages", "all-passed", "stages must be a list"),
        ("stages", [{"name": "S", "status": "passed", "detail": "x"}], "only name/status fields"),
        ("agent.version", "", "agent name/version metadata"),
        ("agent.name", "", "agent name/version metadata"),
        ("agent", _DELETE, "agent name/version metadata"),
        ("failure_taxonomy", [42], "list of non-empty strings"),
        ("failure_taxonomy", ["a", "a"], "must not contain duplicates"),
    ],
)
def test_summary_rejects_malformed_records(
    tmp_path: Path, dotted_path: str, value: Any, fragment: str
) -> None:
    payload = mutated(BASE_PAYLOAD, dotted_path, value)
    path = write_payload(tmp_path, "broken.json", payload)
    with pytest.raises(ReproBenchSummaryError, match=re.escape(fragment)):
        summarize_reprobench_results([path])


def test_summary_taxonomy_semantics_are_enforced(tmp_path: Path) -> None:
    success = mutated(BASE_PAYLOAD, "failure_taxonomy", ["expected_artifact_missing"])
    partial_base = result_payload(report=partial_report())
    partial_empty = mutated(partial_base, "failure_taxonomy", [])
    partial_hard = mutated(partial_base, "failure_taxonomy", ["environment_build_failure"])
    failure_base = result_payload(report=failing_metric_report())
    failure_empty = mutated(failure_base, "failure_taxonomy", [])
    failure_soft = mutated(failure_base, "failure_taxonomy", ["insufficient_evidence_or_execution"])

    cases = [
        (success, "must not declare failure taxonomy"),
        (partial_empty, "exactly the soft"),
        (partial_hard, "exactly the soft"),
        (failure_empty, "hard failure taxonomy"),
        (failure_soft, "must not use the partial-only"),
    ]
    for index, (payload, fragment) in enumerate(cases):
        path = write_payload(tmp_path, f"tax{index}.json", payload)
        with pytest.raises(ReproBenchSummaryError, match=fragment):
            summarize_reprobench_results([path])


def test_summary_file_level_rejections(tmp_path: Path) -> None:
    good = write_payload(tmp_path, "good.json", BASE_PAYLOAD)
    link = tmp_path / "link.json"
    link.symlink_to(good)
    with pytest.raises(ReproBenchSummaryError, match="must not be a symlink"):
        summarize_reprobench_results([link])
    with pytest.raises(ReproBenchSummaryError, match="could not stat result"):
        summarize_reprobench_results([tmp_path / "missing.json"])
    with pytest.raises(ReproBenchSummaryError, match="regular JSON file"):
        summarize_reprobench_results([tmp_path])
    bad_syntax = tmp_path / "syntax.json"
    bad_syntax.write_text("{oops", encoding="utf-8")
    with pytest.raises(ReproBenchSummaryError, match="invalid result JSON"):
        summarize_reprobench_results([bad_syntax])
    nan = tmp_path / "nan.json"
    nan.write_text('{"wall_clock_seconds": NaN}', encoding="utf-8")
    with pytest.raises(ReproBenchSummaryError, match="non-finite JSON number"):
        summarize_reprobench_results([nan])
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(ReproBenchSummaryError, match="must contain an object"):
        summarize_reprobench_results([array])
    huge = tmp_path / "huge.json"
    huge.write_bytes(b"[" * (5 * 1024 * 1024 + 1))
    with pytest.raises(ReproBenchSummaryError, match="aggregation limit"):
        summarize_reprobench_results([huge])


def test_summary_write_creates_parents_and_newline(tmp_path: Path) -> None:
    payload = summarize_reprobench_results([write_payload(tmp_path, "r.json", BASE_PAYLOAD)])
    destination = tmp_path / "nested" / "summary.json"
    assert write_reprobench_summary(payload, destination) == destination
    text = destination.read_text(encoding="utf-8")
    assert text == json.dumps(payload, indent=2) + "\n"


def test_summary_main_exit_code_output_and_determinism(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = write_payload(tmp_path, "r2.json", result_payload())
    second = write_payload(
        tmp_path,
        "r1.json",
        result_payload(
            task=make_task(task_id="case-0002"),
            report=failing_metric_report(),
        ),
    )
    output = tmp_path / "out" / "summary.json"
    argv = [
        "verirepro-reprobench-summary",
        str(first),
        str(second),
        "--output",
        str(output),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert summary_main() == 0
    text = output.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["summary"]["cases"] == 2
    assert data["summary"]["outcomes"] == {"failure": 1, "success": 1}
    assert [item["file"] for item in data["inputs"]] == ["r1.json", "r2.json"]
    stdout = capsys.readouterr().out
    assert "ReproBench summary: cases=2 success=50.0%" in stdout
    assert "zero_intervention=100.0%" in stdout
    assert f"Result: {output}" in stdout

    again = tmp_path / "again.json"
    monkeypatch.setattr(sys, "argv", [*argv[:-1], str(again)])
    assert summary_main() == 0
    assert again.read_text(encoding="utf-8") == text


def test_summary_main_propagates_validation_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = write_payload(tmp_path, "broken.json", mutated(BASE_PAYLOAD, "outcome", "UNKNOWN"))
    monkeypatch.setattr(sys, "argv", ["verirepro-reprobench-summary", str(broken)])
    with pytest.raises(ReproBenchSummaryError, match="invalid outcome"):
        summary_main()


def test_unknown_status_maps_to_declared_partial_not_silent_pass() -> None:
    payload = result_payload(report=make_report(status="MYSTERY"))
    assert payload["outcome"] == "partial"
    assert payload["failure_taxonomy"] == ["insufficient_evidence_or_execution"]
