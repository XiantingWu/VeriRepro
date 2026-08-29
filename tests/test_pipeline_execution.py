from pathlib import Path

import pytest

from reproagent.environment import DockerUnavailableError
from reproagent.experiment import ExperimentTimeoutError
from reproagent.models import ExperimentResult
from reproagent.pipeline_execution import execute_experiment


def _execute(tmp_path: Path, monkeypatch, result_or_error):
    monkeypatch.setattr(
        "reproagent.pipeline_execution.image_tag",
        lambda repository_url, fingerprint: "verirepro:test",
    )
    monkeypatch.setattr(
        "reproagent.pipeline_execution.build_image",
        lambda *args, **kwargs: None,
    )

    if isinstance(result_or_error, BaseException):

        def fail(*args, **kwargs):
            raise result_or_error

        monkeypatch.setattr("reproagent.pipeline_execution.run_in_docker", fail)
    else:
        monkeypatch.setattr(
            "reproagent.pipeline_execution.run_in_docker",
            lambda *args, **kwargs: result_or_error,
        )

    return execute_experiment(
        execute=True,
        run_command="python reproduce.py",
        preexecution_failed=False,
        repository_url="https://github.com/example/project",
        repository_path=tmp_path / "repo",
        dockerfile=tmp_path / "Dockerfile",
        environment_fingerprint="fingerprint",
        workspace=tmp_path,
        output_dir=tmp_path / "outputs",
        dataset_dir=tmp_path / "datasets",
        model_dir=None,
        output_backend="persistent",
        network_enabled=False,
        gpu_enabled=False,
        timeout=10,
    )


def test_non_zero_process_exit_is_a_hard_execution_failure(tmp_path, monkeypatch):
    outcome = _execute(
        tmp_path,
        monkeypatch,
        ExperimentResult(
            command="python reproduce.py",
            exit_code=7,
            stdout="VERIREPRO_METRIC accuracy=0.9\n",
            stderr="boom\n",
            duration_seconds=0.2,
        ),
    )
    assert outcome.failed is True
    assert outcome.reproduced_metrics == {"accuracy": 0.9}
    assert any(
        stage.name == "Experiment executed" and stage.status == "failed" for stage in outcome.stages
    )


def test_process_timeout_is_a_hard_execution_failure(tmp_path, monkeypatch):
    outcome = _execute(
        tmp_path,
        monkeypatch,
        ExperimentTimeoutError("experiment timed out after 10 seconds"),
    )
    assert outcome.failed is True
    assert any("timed out" in stage.detail for stage in outcome.stages)


def test_gpu_runtime_unavailable_is_not_downgraded_to_partial(tmp_path, monkeypatch):
    outcome = _execute(
        tmp_path,
        monkeypatch,
        RuntimeError("could not select device driver with capabilities: [[gpu]]"),
    )
    assert outcome.failed is True
    assert any("device driver" in stage.detail for stage in outcome.stages)


def test_docker_unavailable_records_build_failure_and_skips_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "reproagent.pipeline_execution.image_tag",
        lambda repository_url, fingerprint: "verirepro:test",
    )

    def fail_build(*args, **kwargs):
        raise DockerUnavailableError("Docker is unavailable")

    monkeypatch.setattr("reproagent.pipeline_execution.build_image", fail_build)
    outcome = execute_experiment(
        execute=True,
        run_command="python reproduce.py",
        preexecution_failed=False,
        repository_url="https://github.com/example/project",
        repository_path=tmp_path / "repo",
        dockerfile=tmp_path / "Dockerfile",
        environment_fingerprint="fingerprint",
        workspace=tmp_path,
        output_dir=tmp_path / "outputs",
        dataset_dir=tmp_path / "datasets",
        model_dir=None,
        output_backend="persistent",
        network_enabled=False,
        gpu_enabled=False,
        timeout=10,
    )
    assert outcome.failed is True
    assert [(stage.name, stage.status) for stage in outcome.stages] == [
        ("Environment built", "failed"),
        ("Experiment executed", "skipped"),
    ]


def test_no_execute_never_calls_build(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("build must not be called when execution is disabled")

    monkeypatch.setattr("reproagent.pipeline_execution.build_image", forbidden)
    outcome = execute_experiment(
        execute=False,
        run_command="python reproduce.py",
        preexecution_failed=False,
        repository_url="https://github.com/example/project",
        repository_path=tmp_path / "repo",
        dockerfile=tmp_path / "Dockerfile",
        environment_fingerprint="fingerprint",
        workspace=tmp_path,
        output_dir=tmp_path / "outputs",
        dataset_dir=tmp_path / "datasets",
        model_dir=None,
        output_backend="persistent",
        network_enabled=False,
        gpu_enabled=False,
        timeout=10,
    )
    assert outcome.failed is False
    assert outcome.stages[0].status == "skipped"
