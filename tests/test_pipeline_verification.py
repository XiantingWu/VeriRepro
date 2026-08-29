from pathlib import Path

from reproagent.config import ArtifactSpec, MetricSpec, ReproManifest
from reproagent.models import ArtifactComparison, OutputArtifact
from reproagent.pipeline_verification import verify_results


def _manifest(*, artifacts=(), metrics=()):
    return ReproManifest(
        command="python reproduce.py",
        network=False,
        datasets=(),
        metrics=metrics,
        artifacts=artifacts,
        scientific_contract_trusted=True,
        declared_metric_count=len(metrics),
        declared_artifact_count=len(artifacts),
    )


def test_no_verified_result_remains_partial(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("reproagent.pipeline_verification.index_outputs", lambda path: ())
    outcome = verify_results(
        manifest=_manifest(),
        execute=True,
        repository_path=tmp_path / "repo",
        workspace=tmp_path,
        output_dir=tmp_path / "outputs",
        paper_metrics={},
        reproduced_metrics={},
        metric_specs=(),
        execution_failed=False,
    )
    assert outcome.status == "PARTIAL"
    assert outcome.failed is False


def test_metric_unavailable_does_not_invent_a_pass(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("reproagent.pipeline_verification.index_outputs", lambda path: ())
    spec = MetricSpec(name="accuracy", paper=0.9, tolerance=0.01)
    outcome = verify_results(
        manifest=_manifest(metrics=(spec,)),
        execute=True,
        repository_path=tmp_path / "repo",
        workspace=tmp_path,
        output_dir=tmp_path / "outputs",
        paper_metrics={"accuracy": 0.9},
        reproduced_metrics={},
        metric_specs=(spec,),
        execution_failed=False,
    )
    assert outcome.status == "PARTIAL"
    assert outcome.metric_comparisons == ()


def test_metric_mismatch_is_fail(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("reproagent.pipeline_verification.index_outputs", lambda path: ())
    spec = MetricSpec(name="accuracy", paper=0.9, tolerance=0.01)
    outcome = verify_results(
        manifest=_manifest(metrics=(spec,)),
        execute=True,
        repository_path=tmp_path / "repo",
        workspace=tmp_path,
        output_dir=tmp_path / "outputs",
        paper_metrics={"accuracy": 0.9},
        reproduced_metrics={"accuracy": 0.7},
        metric_specs=(spec,),
        execution_failed=False,
    )
    assert outcome.status == "FAIL"
    assert outcome.metric_comparisons[0].passed is False


def test_artifact_mismatch_is_fail(tmp_path: Path, monkeypatch):
    spec = ArtifactSpec(
        name="figure",
        kind="file",
        reference="references/figure.png",
        reproduced="figure.png",
    )
    artifact = OutputArtifact(
        path="figure.png",
        kind="file",
        size_bytes=3,
        sha256="0" * 64,
    )
    mismatch = ArtifactComparison(
        name="figure",
        kind="file",
        reference="references/figure.png",
        reproduced="figure.png",
        score=0.0,
        threshold=0.95,
        passed=False,
        detail="content mismatch",
    )
    monkeypatch.setattr(
        "reproagent.pipeline_verification.index_outputs",
        lambda path: (artifact,),
    )
    monkeypatch.setattr(
        "reproagent.pipeline_verification.compare_artifacts",
        lambda *args, **kwargs: (mismatch,),
    )
    monkeypatch.setattr(
        "reproagent.pipeline_verification.write_artifact_results",
        lambda *args, **kwargs: None,
    )
    outcome = verify_results(
        manifest=_manifest(artifacts=(spec,)),
        execute=True,
        repository_path=tmp_path / "repo",
        workspace=tmp_path,
        output_dir=tmp_path / "outputs",
        paper_metrics={},
        reproduced_metrics={},
        metric_specs=(),
        execution_failed=False,
    )
    assert outcome.status == "FAIL"
    assert outcome.artifact_comparisons[0].passed is False


def test_missing_artifact_fails_closed(tmp_path: Path, monkeypatch):
    spec = ArtifactSpec(
        name="table",
        kind="table",
        reference="references/table.csv",
        reproduced="table.csv",
    )
    monkeypatch.setattr("reproagent.pipeline_verification.index_outputs", lambda path: ())

    def missing(*args, **kwargs):
        raise FileNotFoundError("reproduced artifact is missing: table.csv")

    monkeypatch.setattr("reproagent.pipeline_verification.compare_artifacts", missing)
    outcome = verify_results(
        manifest=_manifest(artifacts=(spec,)),
        execute=True,
        repository_path=tmp_path / "repo",
        workspace=tmp_path,
        output_dir=tmp_path / "outputs",
        paper_metrics={},
        reproduced_metrics={},
        metric_specs=(),
        execution_failed=False,
    )
    assert outcome.status == "FAIL"
    assert outcome.failed is True
    assert any(
        stage.name == "Artifact verification safety"
        and stage.status == "failed"
        and "missing" in stage.detail
        for stage in outcome.stages
    )


def test_output_index_failure_is_fail_closed(tmp_path: Path, monkeypatch):
    def fail(path):
        raise RuntimeError("artifact budget exceeded")

    monkeypatch.setattr("reproagent.pipeline_verification.index_outputs", fail)
    outcome = verify_results(
        manifest=_manifest(),
        execute=True,
        repository_path=tmp_path / "repo",
        workspace=tmp_path,
        output_dir=tmp_path / "outputs",
        paper_metrics={},
        reproduced_metrics={},
        metric_specs=(),
        execution_failed=False,
    )
    assert outcome.status == "FAIL"
    assert outcome.output_index_failed is True


def test_host_artifact_contract_uses_separate_reference_root(tmp_path: Path, monkeypatch):
    repository = tmp_path / "repo"
    references = tmp_path / "trusted-references"
    outputs = tmp_path / "outputs"
    repository.mkdir()
    references.mkdir()
    outputs.mkdir()
    spec = ArtifactSpec(
        name="paper-table",
        kind="table",
        reference="paper.csv",
        reproduced="run.csv",
        threshold=1.0,
    )
    artifact = OutputArtifact(path="run.csv", kind="table", size_bytes=1, sha256="0" * 64)
    passed = ArtifactComparison(
        name="paper-table",
        kind="table",
        reference="paper.csv",
        reproduced="run.csv",
        score=1.0,
        threshold=1.0,
        passed=True,
        detail="paper-grounded match",
    )
    monkeypatch.setattr("reproagent.pipeline_verification.index_outputs", lambda path: (artifact,))

    captured = {}

    def compare(specs, reference_root, output_root):
        captured["reference_root"] = reference_root
        captured["output_root"] = output_root
        return (passed,)

    monkeypatch.setattr("reproagent.pipeline_verification.compare_artifacts", compare)
    monkeypatch.setattr(
        "reproagent.pipeline_verification.write_artifact_results",
        lambda *args, **kwargs: None,
    )
    outcome = verify_results(
        manifest=_manifest(),
        execute=True,
        repository_path=repository,
        workspace=tmp_path,
        output_dir=outputs,
        paper_metrics={},
        reproduced_metrics={},
        metric_specs=(),
        execution_failed=False,
        artifact_specs=(spec,),
        artifact_reference_root=references,
    )
    assert captured["reference_root"] == references
    assert captured["output_root"] == outputs
    assert outcome.status == "PASS"
    assert outcome.artifact_comparisons == (passed,)
