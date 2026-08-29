from types import SimpleNamespace

from reproagent.config import ReproManifest
from reproagent.intelligence import MetricClaim
from reproagent.models import (
    DiscoveryResult,
    EnvironmentPlan,
    PaperDocument,
    PaperReference,
    RepositoryCandidate,
    RepositoryProfile,
    StageResult,
)
from reproagent.pipeline import _auto_verdict_metrics, _effective_gpu, _effective_network, reproduce
from reproagent.pipeline_execution import ExecutionOutcome
from reproagent.pipeline_verification import VerificationOutcome


def test_network_and_gpu_require_manifest_request_and_user_authorization():
    assert _effective_network(True, True) is True
    assert _effective_network(True, False) is False
    assert _effective_network(False, True) is False
    assert _effective_gpu(True, True) is True
    assert _effective_gpu(True, False) is False


def test_auto_verdict_metrics_reject_conflicting_grounded_claims():
    intelligence = SimpleNamespace(
        metrics=(
            MetricClaim("accuracy", 0.90, 0.5, 1, "accuracy 90%", "verified"),
            MetricClaim("acc", 0.91, 0.5, 2, "acc 91%", "verified"),
        )
    )
    paper_metrics, specs, excluded = _auto_verdict_metrics(intelligence)
    assert paper_metrics == {}
    assert specs == ()
    assert "accuracy" in excluded


def test_auto_verdict_metrics_use_fixed_tolerance_not_llm_tolerance():
    intelligence = SimpleNamespace(
        metrics=(MetricClaim("accuracy", 0.9, 0.5, 1, "accuracy 90%", "verified"),)
    )
    paper_metrics, specs, excluded = _auto_verdict_metrics(intelligence)
    assert paper_metrics == {"accuracy": 0.9}
    assert specs[0].tolerance == 0.01
    assert excluded == ()


def test_reproduce_wires_orchestration_layers_without_network_or_docker(tmp_path, monkeypatch):
    repository_url = "https://github.com/example/project"
    paper = PaperDocument(
        reference=PaperReference(raw="paper.pdf", kind="local-pdf", identifier="paper.pdf"),
        pdf_path=tmp_path / "paper.pdf",
        text=f"Our code is available at {repository_url}",
        metadata={"pages": [f"Our code is available at {repository_url}"], "page_count": 1},
    )
    discovery = DiscoveryResult(
        github_repositories=(repository_url,),
        dataset_urls=(),
        repository_candidates=(
            RepositoryCandidate(repository_url, score=10, occurrences=1, reasons=("our code",)),
        ),
    )
    profile = RepositoryProfile(
        path=tmp_path / "repository",
        stacks=("Python",),
        dependency_files=("requirements.txt",),
        manifest_path=None,
        suggested_command=None,
        commit_sha="a" * 40,
        python_requirement=">=3.11",
        dependency_strategy="requirements",
        fingerprint="repo-fingerprint",
    )
    environment = EnvironmentPlan(
        python_version="3.11",
        python_source="repository-specifier",
        python_requirement=">=3.11",
        dependency_strategy="requirements",
        dependency_files=("requirements.txt",),
        commit_sha="a" * 40,
        repository_fingerprint="repo-fingerprint",
        environment_fingerprint="environment-fingerprint",
        gpu_likely=False,
        cuda_hints=(),
        reproducibility_grade="strong",
        warnings=(),
    )
    manifest = ReproManifest(
        command="python reproduce.py",
        network=False,
        datasets=(),
        metrics=(),
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr("reproagent.pipeline.allocate_workspace", lambda root, source: tmp_path)
    monkeypatch.setattr("reproagent.pipeline.resolve_paper", lambda source, workspace: paper)
    monkeypatch.setattr("reproagent.pipeline.discover_paper_artifacts", lambda value: discovery)
    monkeypatch.setattr("reproagent.pipeline.write_discovery", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "reproagent.pipeline.clone_repository",
        lambda url, destination, ref=None: tmp_path / "repository",
    )
    monkeypatch.setattr("reproagent.pipeline.inspect_repository", lambda repo: profile)
    monkeypatch.setattr("reproagent.pipeline.load_manifest", lambda *args, **kwargs: manifest)
    monkeypatch.setattr("reproagent.pipeline.plan_environment", lambda *args, **kwargs: environment)
    monkeypatch.setattr("reproagent.pipeline.write_environment_plan", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "reproagent.pipeline.generate_dockerfile",
        lambda *args, **kwargs: tmp_path / "Dockerfile.verirepro",
    )
    monkeypatch.setattr(
        "reproagent.pipeline.execute_experiment",
        lambda **kwargs: ExecutionOutcome(
            stages=(StageResult("Experiment executed", "passed", "exit=0"),),
            reproduced_metrics={},
            failed=False,
        ),
    )

    def verify(**kwargs):
        captured["verify"] = kwargs
        return VerificationOutcome(
            stages=(StageResult("Results compared", "skipped", "no evidence"),),
            output_artifacts=(),
            artifact_comparisons=(),
            metric_comparisons=(),
            output_index_failed=False,
            failed=False,
            status="PARTIAL",
        )

    monkeypatch.setattr("reproagent.pipeline.verify_results", verify)

    def completed(**kwargs):
        captured["report"] = kwargs
        return SimpleNamespace(status=kwargs["status"], stages=kwargs["stages"])

    monkeypatch.setattr("reproagent.pipeline.write_completed_report", completed)

    report = reproduce(
        "paper.pdf",
        workspace_root=tmp_path,
        execute=True,
        use_llm=False,
    )

    assert report.status == "PARTIAL"
    verify_args = captured["verify"]
    report_args = captured["report"]
    assert isinstance(verify_args, dict)
    assert isinstance(report_args, dict)
    assert verify_args["execution_failed"] is False
    assert verify_args["repository_path"] == tmp_path / "repository"
    assert report_args["repository"] == repository_url
    stage_names = [stage.name for stage in report_args["stages"]]
    assert "Paper resolved" in stage_names
    assert "Repository inspected" in stage_names
    assert "Environment planned" in stage_names
    assert "Network policy" in stage_names
    assert "GPU policy" in stage_names
    assert "Experiment executed" in stage_names
    assert "Results compared" in stage_names


def test_reproduce_paper_resolution_failure_writes_terminal_failure(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fail(*args, **kwargs):
        raise RuntimeError("PDF malformed")

    monkeypatch.setattr("reproagent.pipeline.allocate_workspace", lambda root, source: tmp_path)
    monkeypatch.setattr("reproagent.pipeline.resolve_paper", fail)

    def failure(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="FAIL", stages=kwargs["stages"])

    monkeypatch.setattr("reproagent.pipeline.write_failure_report", failure)
    report = reproduce("broken.pdf", workspace_root=tmp_path)
    assert report.status == "FAIL"
    assert captured["repository"] is None
    stages = captured["stages"]
    assert isinstance(stages, list)
    assert stages[0].name == "Paper resolved"
    assert stages[0].status == "failed"
    assert "PDF malformed" in stages[0].detail
