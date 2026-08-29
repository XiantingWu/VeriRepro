from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .environment import DockerUnavailableError, build_image, image_tag
from .experiment import run_in_docker
from .metrics import extract_output_metrics
from .models import StageResult


@dataclass(frozen=True)
class ExecutionOutcome:
    stages: tuple[StageResult, ...]
    reproduced_metrics: dict[str, float]
    failed: bool


def execute_experiment(
    *,
    execute: bool,
    run_command: str | None,
    preexecution_failed: bool,
    repository_url: str,
    repository_path: Path,
    dockerfile: Path,
    environment_fingerprint: str,
    workspace: Path,
    output_dir: Path,
    dataset_dir: Path,
    model_dir: Path | None,
    output_backend: str,
    network_enabled: bool,
    gpu_enabled: bool,
    timeout: int,
) -> ExecutionOutcome:
    """Build and run the third-party experiment without deciding scientific truth.

    This layer owns environment build/runtime mechanics and log capture only. It
    deliberately does not compare metrics/artifacts or decide PASS/PARTIAL/FAIL.
    """
    stages: list[StageResult] = []
    reproduced_metrics: dict[str, float] = {}
    failed = bool(preexecution_failed)

    if execute and run_command and not preexecution_failed:
        try:
            tag = image_tag(repository_url, environment_fingerprint)
            build_image(repository_path, dockerfile, tag, timeout=timeout)
            stages.append(StageResult("Environment built", "passed", f"Docker image {tag}"))
            result = run_in_docker(
                tag,
                run_command,
                output_dir,
                dataset_dir,
                model_dir,
                output_backend=output_backend,
                network=network_enabled,
                gpu=gpu_enabled,
                timeout=timeout,
            )
            (workspace / "experiment.stdout.log").write_text(result.stdout, encoding="utf-8")
            (workspace / "experiment.stderr.log").write_text(result.stderr, encoding="utf-8")
            if result.succeeded:
                stages.append(
                    StageResult(
                        "Experiment executed",
                        "passed",
                        f"exit=0 in {result.duration_seconds:.1f}s using `{run_command}`",
                    )
                )
            else:
                failed = True
                stages.append(
                    StageResult(
                        "Experiment executed",
                        "failed",
                        f"exit={result.exit_code}; see experiment.stderr.log",
                    )
                )
            reproduced_metrics = extract_output_metrics(result.stdout + "\n" + result.stderr)
        except DockerUnavailableError as exc:
            failed = True
            stages.append(StageResult("Environment built", "failed", str(exc)))
            stages.append(
                StageResult(
                    "Experiment executed",
                    "skipped",
                    "environment build failed; experiment was not started",
                )
            )
        except Exception as exc:
            failed = True
            stages.append(StageResult("Experiment executed", "failed", str(exc)))
    elif execute and run_command and preexecution_failed:
        stages.append(
            StageResult(
                "Experiment executed",
                "skipped",
                "a required pre-execution stage failed; experiment was not started",
            )
        )
    elif not execute:
        stages.append(
            StageResult("Experiment executed", "skipped", "execution disabled by --no-execute")
        )
    else:
        stages.append(
            StageResult(
                "Experiment executed",
                "skipped",
                "no safe reproduction command found; add verirepro.yaml, use --command, "
                "or enable grounded repository planning",
            )
        )

    return ExecutionOutcome(
        stages=tuple(stages),
        reproduced_metrics=reproduced_metrics,
        failed=failed,
    )
