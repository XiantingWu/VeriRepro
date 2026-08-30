from __future__ import annotations

import json
import os
import shutil
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

import reproagent
from reproagent import cli
from reproagent.core import build_reproduction_plan
from reproagent.llm import LLMUnavailableError
from reproagent.models import EnvironmentPlan, StageResult
from reproagent.workspaces import allocate_workspace, safe_workspace_slug

REPO_ROOT = Path(__file__).resolve().parents[1]


class ConfiguredLLMConfig:
    base_url = "https://llm.example/v1"
    api_key = "secret-key"
    model = "gpt-test"

    @classmethod
    def from_env(cls, *, model: str | None = None) -> ConfiguredLLMConfig:
        return cls()


class UnconfiguredLLMConfig:
    @classmethod
    def from_env(cls, *, model: str | None = None) -> None:
        return None


class BrokenLLMConfig:
    @classmethod
    def from_env(cls, *, model: str | None = None) -> ConfiguredLLMConfig:
        raise LLMUnavailableError("LiteLLM endpoint misconfigured")


class FakeIntelligence:
    grounded_claim_count = 7
    reproduction_completeness = 0.75
    ambiguities = ("seed", "split")

    def to_dict(self) -> dict[str, object]:
        return {
            "grounded_claim_count": self.grounded_claim_count,
            "reproduction_completeness": self.reproduction_completeness,
            "ambiguities": list(self.ambiguities),
        }


def fake_environment_plan() -> EnvironmentPlan:
    return EnvironmentPlan(
        python_version="3.11.9",
        python_source="repository-file",
        python_requirement=">=3.11",
        dependency_strategy="requirements-lock",
        dependency_files=("requirements.txt",),
        commit_sha="abc123def0",
        repository_fingerprint="repo-fp",
        environment_fingerprint="0123456789abcdef7890",
        gpu_likely=False,
        cuda_hints=(),
        reproducibility_grade="strong",
        warnings=("no lockfile hash",),
    )


def minimal_fake_report() -> SimpleNamespace:
    return SimpleNamespace(
        stages=(),
        paper_intelligence=None,
        environment_plan=None,
        artifact_comparisons=(),
        comparisons=(),
        status="passed",
        report_markdown="",
        to_dict=lambda: {"status": "passed"},
    )


def full_fake_report() -> SimpleNamespace:
    stages = (
        StageResult("resolve", "passed", "ok"),
        StageResult("execute", "failed", "boom"),
        StageResult("datasets", "skipped", "none declared"),
        StageResult("weird", "curious", "?"),
    )
    return SimpleNamespace(
        stages=stages,
        paper_intelligence={
            "task": "classify",
            "ambiguities": ["a", "b", "c"],
            "reproduction_completeness": 0.5,
        },
        environment_plan={
            "python_version": "3.11.9",
            "dependency_strategy": "requirements-lock",
            "reproducibility_grade": "strong",
            "commit_sha": "abc123",
            "environment_fingerprint": "0123456789abcdef7890",
        },
        artifact_comparisons=(
            SimpleNamespace(kind="figure", name="fig1", passed=True, score=0.98, threshold=0.9),
            SimpleNamespace(kind="table", name="tbl1", passed=False, score=0.1, threshold=0.9),
        ),
        comparisons=(
            SimpleNamespace(name="accuracy", paper=0.91, reproduced=0.88, difference=-0.03),
        ),
        status="failed",
        report_markdown="# Report",
        to_dict=lambda: {"status": "failed"},
    )


def run_cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str):
    monkeypatch.setattr(sys, "argv", ["verirepro", *argv])
    code: object = 0
    try:
        cli.main()
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return (0 if code is None else code), captured.out, captured.err


def patch_which(monkeypatch: pytest.MonkeyPatch, tools: dict[str, str]) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: tools.get(name))


# --- top-level parser surface -------------------------------------------------


def test_version_flag_prints_version_and_exits_zero(monkeypatch, capsys) -> None:
    code, out, err = run_cli(monkeypatch, capsys, "--version")
    assert code == 0
    assert err == ""
    assert out.strip() == f"VeriRepro {reproagent.__version__}"


def test_top_level_help_lists_all_subcommands(monkeypatch, capsys) -> None:
    code, out, err = run_cli(monkeypatch, capsys, "--help")
    assert code == 0
    assert err == ""
    assert "usage: verirepro" in out
    assert "Evidence-grounded" in out
    for subcommand in ("plan", "analyze", "inspect", "reproduce", "doctor"):
        assert subcommand in out


@pytest.mark.parametrize(
    ("argv", "markers"),
    [
        (
            ("reproduce", "--help"),
            ("--allow-gpu", "--trust-repository-contract", "--output-backend"),
        ),
        (("analyze", "--help"), ("--model", "--workspace", "--json")),
        (("doctor", "--help"), ("--strict", "--require-llm")),
    ],
)
def test_subcommand_help_documents_flags(monkeypatch, capsys, argv, markers) -> None:
    code, out, _ = run_cli(monkeypatch, capsys, *argv)
    assert code == 0
    for marker in markers:
        assert marker in out


def test_missing_subcommand_exits_two_with_stderr_usage(monkeypatch, capsys) -> None:
    code, out, err = run_cli(monkeypatch, capsys)
    assert code == 2
    assert out == ""
    assert "the following arguments are required: subcommand" in err


def test_unknown_subcommand_exits_two_with_invalid_choice(monkeypatch, capsys) -> None:
    code, _, err = run_cli(monkeypatch, capsys, "frobnicate")
    assert code == 2
    assert "invalid choice: 'frobnicate'" in err


def test_plan_requires_paper_argument(monkeypatch, capsys) -> None:
    code, _, err = run_cli(monkeypatch, capsys, "plan")
    assert code == 2
    assert "arguments are required: paper" in err


def test_reproduce_rejects_invalid_output_backend_choice(monkeypatch, capsys) -> None:
    code, _, err = run_cli(monkeypatch, capsys, "reproduce", "paper-x", "--output-backend", "tmpfs")
    assert code == 2
    assert "invalid choice: 'tmpfs'" in err


def test_reproduce_timeout_must_be_an_integer(monkeypatch, capsys) -> None:
    code, _, err = run_cli(monkeypatch, capsys, "reproduce", "paper-x", "--timeout", "soon")
    assert code == 2
    assert "invalid int value: 'soon'" in err


# --- plan dispatch -------------------------------------------------------------


def test_plan_prints_pipeline_json_for_stripped_reference(monkeypatch, capsys) -> None:
    code, out, err = run_cli(monkeypatch, capsys, "plan", "  arXiv:2401.00001 \n")
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["paper"] == "arXiv:2401.00001"
    assert len(payload["stages"]) == 8
    assert payload["stages"][0] == "resolve-paper"


def test_console_script_entrypoints_resolve_to_importable_mains() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["reproagent"] == "reproagent.cli:main"
    assert scripts["verirepro"] == "verirepro.cli:main"

    from verirepro import cli as verirepro_cli

    assert callable(cli.main)
    assert verirepro_cli.main is cli.main


# --- analyze dispatch ----------------------------------------------------------


def test_analyze_human_success_writes_artifacts_into_allocated_workspace(
    monkeypatch, capsys, tmp_path
) -> None:
    seen: dict[str, object] = {}
    workspace_box: dict[str, Path] = {}

    def fake_resolve_paper(raw, workspace):
        seen["raw"] = raw
        workspace_box["root"] = Path(workspace).parent
        return SimpleNamespace(pdf_path=str(Path(workspace) / "paper.pdf"))

    def fake_write_discovery(discovery, destination):
        seen["discovery_dest"] = destination
        return Path(destination)

    def fake_analyze_paper(paper, repositories, model=None):
        seen["repositories"] = repositories
        seen["model"] = model
        return FakeIntelligence()

    def fake_write_intelligence(analysis, destination):
        seen["intelligence_dest"] = destination
        return Path(destination)

    discovery = SimpleNamespace(github_repositories=("repo-a",))
    monkeypatch.setattr(cli, "resolve_paper", fake_resolve_paper)
    monkeypatch.setattr(cli, "discover_paper_artifacts", lambda paper: discovery)
    monkeypatch.setattr(cli, "write_discovery", fake_write_discovery)
    monkeypatch.setattr(cli, "analyze_paper", fake_analyze_paper)
    monkeypatch.setattr(cli, "write_intelligence", fake_write_intelligence)

    target = tmp_path / "analysis-root"
    code, out, err = run_cli(
        monkeypatch, capsys, "analyze", "2401.00001", "--workspace", str(target)
    )

    assert code == 0
    assert err == ""
    root = workspace_box["root"]
    assert root.parent == target
    assert root.name.startswith("2401.00001-")
    assert seen["raw"] == "2401.00001"
    assert seen["repositories"] == ("repo-a",)
    assert seen["model"] is None
    assert Path(seen["discovery_dest"]) == root / "artifact-discovery.json"
    assert Path(seen["intelligence_dest"]) == root / "paper-intelligence.json"
    assert root.is_dir()
    assert "✓ Paper:" in out
    assert "✓ Grounded claims: 7" in out
    assert "✓ Critical-field completeness: 75%" in out
    assert "✓ Ambiguities: 2" in out
    assert f"Output: {root / 'paper-intelligence.json'}" in out


def test_analyze_json_flag_prints_intelligence_dict(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(cli, "resolve_paper", lambda raw, ws: SimpleNamespace(pdf_path="p.pdf"))
    discovery = SimpleNamespace(github_repositories=())
    monkeypatch.setattr(cli, "discover_paper_artifacts", lambda paper: discovery)
    monkeypatch.setattr(cli, "write_discovery", lambda discovery, dest: Path(dest))
    monkeypatch.setattr(cli, "analyze_paper", lambda paper, repos, model=None: FakeIntelligence())
    monkeypatch.setattr(cli, "write_intelligence", lambda analysis, dest: Path(dest))

    code, out, _ = run_cli(
        monkeypatch, capsys, "analyze", "2401.00001", "--json", "--model", "custom-model"
    )

    assert code == 0
    payload = json.loads(out)
    assert payload == {
        "grounded_claim_count": 7,
        "reproduction_completeness": 0.75,
        "ambiguities": ["seed", "split"],
    }
    assert json.loads(out)["reproduction_completeness"] == 0.75


def test_analyze_llm_error_exits_nonzero_with_message(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(cli, "resolve_paper", lambda raw, ws: SimpleNamespace(pdf_path="p.pdf"))
    monkeypatch.setattr(
        cli, "discover_paper_artifacts", lambda paper: SimpleNamespace(github_repositories=())
    )
    monkeypatch.setattr(cli, "write_discovery", lambda discovery, dest: Path(dest))

    def boom(paper, repositories, model=None):
        raise LLMUnavailableError("no LiteLLM endpoint configured")

    monkeypatch.setattr(cli, "analyze_paper", boom)

    code, out, err = run_cli(
        monkeypatch, capsys, "analyze", "2401.00001", "--workspace", str(tmp_path)
    )

    assert code != 0
    assert isinstance(code, str)
    assert "no LiteLLM endpoint configured" in code
    assert err == ""


def test_analyze_unconfigured_litellm_exits_nonzero_with_hint(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setattr(cli, "resolve_paper", lambda raw, ws: SimpleNamespace(pdf_path="p.pdf"))
    monkeypatch.setattr(
        cli, "discover_paper_artifacts", lambda paper: SimpleNamespace(github_repositories=())
    )
    monkeypatch.setattr(cli, "write_discovery", lambda discovery, dest: Path(dest))
    monkeypatch.setattr(cli, "analyze_paper", lambda paper, repos, model=None: None)

    code, _, err = run_cli(
        monkeypatch, capsys, "analyze", "2401.00001", "--workspace", str(tmp_path)
    )

    assert code != 0
    assert isinstance(code, str)
    assert "LiteLLM is not configured" in code
    assert "VERIREPRO_LITELLM_BASE_URL" in code
    assert err == ""


# --- inspect dispatch ----------------------------------------------------------


def _patch_inspect_chain(monkeypatch, seen, plan=None) -> None:
    def fake_clone(url, destination, ref=None):
        seen["url"] = url
        seen["destination"] = destination
        seen["ref"] = ref
        return destination

    def fake_inspect(repo):
        seen["repo"] = repo
        return SimpleNamespace()

    def fake_plan(profile, requested_python="auto"):
        seen["requested_python"] = requested_python
        return plan if plan is not None else fake_environment_plan()

    def fake_write(plan_obj, destination):
        seen["plan_dest"] = destination
        return Path(destination)

    monkeypatch.setattr(cli, "clone_repository", fake_clone)
    monkeypatch.setattr(cli, "inspect_repository", fake_inspect)
    monkeypatch.setattr(cli, "plan_environment", fake_plan)
    monkeypatch.setattr(cli, "write_environment_plan", fake_write)


def test_inspect_human_output_includes_warnings_and_contract(monkeypatch, capsys, tmp_path) -> None:
    seen: dict[str, object] = {}
    _patch_inspect_chain(monkeypatch, seen)

    target = tmp_path / "inspect-root"
    code, out, err = run_cli(
        monkeypatch,
        capsys,
        "inspect",
        "https://github.com/org/repo",
        "--ref",
        "v1.2",
        "--python",
        "3.12",
        "--workspace",
        str(target),
    )

    assert code == 0
    assert err == ""
    root = Path(seen["destination"]).parent
    assert root.parent == target
    assert seen["url"] == "https://github.com/org/repo"
    assert seen["ref"] == "v1.2"
    assert Path(seen["destination"]) == root / "repository"
    assert seen["repo"] is seen["destination"]
    assert seen["requested_python"] == "3.12"
    assert Path(seen["plan_dest"]) == root / "environment-plan.json"
    assert "✓ Repository commit: abc123def0" in out
    assert "✓ Python: 3.11.9 (repository-file)" in out
    assert "✓ Dependency strategy: requirements-lock" in out
    assert "✓ Reproducibility grade: STRONG" in out
    assert "✓ GPU likely: False" in out
    assert "! no lockfile hash" in out
    assert f"Output: {root / 'environment-plan.json'}" in out


def test_inspect_json_output_matches_environment_plan_dict(monkeypatch, capsys, tmp_path) -> None:
    seen: dict[str, object] = {}
    _patch_inspect_chain(monkeypatch, seen)

    code, out, err = run_cli(
        monkeypatch, capsys, "inspect", "https://github.com/org/repo", "--json"
    )

    assert code == 0
    assert err == ""
    expected = json.loads(json.dumps(fake_environment_plan().to_dict()))
    payload = json.loads(out)
    assert payload == expected
    assert payload["commit_sha"] == "abc123def0"
    assert seen["ref"] is None
    assert seen["requested_python"] == "auto"


# --- reproduce dispatch --------------------------------------------------------


def test_reproduce_default_delegation_contract(monkeypatch, capsys) -> None:
    seen: dict[str, object] = {}

    def fake_reproduce(source, **kwargs):
        seen["source"] = source
        seen.update(kwargs)
        return minimal_fake_report()

    monkeypatch.setattr(cli, "reproduce", fake_reproduce)

    code, out, err = run_cli(monkeypatch, capsys, "reproduce", "10.1234/does-it")

    assert code == 0
    assert err == ""
    assert seen["source"] == "10.1234/does-it"
    assert seen.pop("source") is not None
    expected = {
        "workspace_root": Path(".verirepro/runs"),
        "repository_url": None,
        "repository_ref": None,
        "command": None,
        "execute": True,
        "python_version": "auto",
        "timeout": 1800,
        "use_llm": True,
        "llm_model": None,
        "allow_network": False,
        "allow_gpu": False,
        "output_backend": "persistent",
        "trust_repository_contract": None,
    }
    assert seen == expected
    assert "Reproducibility: passed" in out


def test_reproduce_forwards_every_override_flag(monkeypatch, capsys, tmp_path) -> None:
    seen: dict[str, object] = {}

    def fake_reproduce(source, **kwargs):
        seen["source"] = source
        seen.update(kwargs)
        return minimal_fake_report()

    monkeypatch.setattr(cli, "reproduce", fake_reproduce)

    workspace = tmp_path / "runs"
    code, _, _ = run_cli(
        monkeypatch,
        capsys,
        "reproduce",
        "paper-x",
        "--repo",
        "org/repo",
        "--ref",
        "v2",
        "--command",
        "make run",
        "--workspace",
        str(workspace),
        "--python",
        "3.12",
        "--timeout",
        "99",
        "--no-execute",
        "--no-llm",
        "--model",
        "model-z",
        "--output-backend",
        "ephemeral",
        "--allow-network",
        "--allow-gpu",
        "--trust-repository-contract",
    )

    assert code == 0
    assert seen == {
        "source": "paper-x",
        "workspace_root": workspace,
        "repository_url": "org/repo",
        "repository_ref": "v2",
        "command": "make run",
        "execute": False,
        "python_version": "3.12",
        "timeout": 99,
        "use_llm": False,
        "llm_model": "model-z",
        "allow_network": True,
        "allow_gpu": True,
        "output_backend": "ephemeral",
        "trust_repository_contract": True,
    }


def test_reproduce_json_flag_prints_report_dict(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "reproduce", lambda source, **kwargs: full_fake_report())

    code, out, err = run_cli(monkeypatch, capsys, "reproduce", "paper-x", "--json")

    assert code == 0
    assert err == ""
    assert json.loads(out) == {"status": "failed"}


def test_reproduce_human_report_renders_all_sections(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "reproduce", lambda source, **kwargs: full_fake_report())

    code, out, _ = run_cli(monkeypatch, capsys, "reproduce", "paper-x")

    assert code == 0
    assert "✓ resolve: ok" in out
    assert "✗ execute: boom" in out
    assert "○ datasets: none declared" in out
    assert "• weird: ?" in out
    assert "Task: classify" in out
    assert "Critical-field completeness: 50%" in out
    assert "Ambiguities: 3" in out
    assert "Environment: Python 3.11.9 / requirements-lock / STRONG" in out
    assert "Commit: abc123" in out
    assert "Fingerprint: 0123456789abcdef" in out
    assert "Artifacts:" in out
    assert "Figure  fig1: 0.980 / 0.900  PASS" in out
    assert "Table   tbl1: 0.100 / 0.900  FAIL" in out
    assert "Accuracy  Paper: 0.9100" in out
    assert "Reproduced: 0.8800" in out
    assert "Difference: -0.0300" in out
    assert "Reproducibility: failed" in out
    assert "Report: # Report" in out


# --- doctor dispatch -----------------------------------------------------------


def test_doctor_ready_human_output_exits_zero(monkeypatch, capsys) -> None:
    patch_which(monkeypatch, {"git": "/usr/bin/git", "docker": "/usr/bin/docker"})
    monkeypatch.setattr(cli, "docker_available", lambda: True)
    monkeypatch.setattr(cli, "LLMConfig", ConfiguredLLMConfig)
    monkeypatch.delenv("VERIREPRO_TRUST_REPOSITORY_CONTRACT", raising=False)

    code, out, err = run_cli(monkeypatch, capsys, "doctor")

    assert code == 0
    assert err == ""
    assert f"VeriRepro: {reproagent.__version__}" in out
    assert "Git: /usr/bin/git" in out
    assert "Docker: /usr/bin/docker" in out
    assert "Docker daemon: True" in out
    assert "LiteLLM configured: True" in out
    assert "LiteLLM model: gpt-test" in out
    assert "Ready: True" in out
    assert "Missing/failed requirement(s):" not in out


def test_doctor_strict_exits_two_when_docker_is_missing(monkeypatch, capsys) -> None:
    patch_which(monkeypatch, {"git": "/usr/bin/git"})
    monkeypatch.setattr(cli, "docker_available", lambda: False)
    monkeypatch.setattr(cli, "LLMConfig", ConfiguredLLMConfig)

    code, out, _ = run_cli(monkeypatch, capsys, "doctor", "--strict")

    assert code == 2
    assert "Ready: False" in out
    assert "Missing/failed requirement(s): docker" in out


def test_doctor_strict_exits_two_when_docker_daemon_is_down(monkeypatch, capsys) -> None:
    patch_which(monkeypatch, {"git": "/usr/bin/git", "docker": "/usr/bin/docker"})
    monkeypatch.setattr(cli, "docker_available", lambda: False)
    monkeypatch.setattr(cli, "LLMConfig", ConfiguredLLMConfig)

    code, out, _ = run_cli(monkeypatch, capsys, "doctor", "--strict")

    assert code == 2
    assert "Missing/failed requirement(s): docker_daemon" in out


def test_doctor_require_llm_reports_missing_litellm_without_strict_exit(
    monkeypatch, capsys
) -> None:
    patch_which(monkeypatch, {"git": "/usr/bin/git", "docker": "/usr/bin/docker"})
    monkeypatch.setattr(cli, "docker_available", lambda: True)
    monkeypatch.setattr(cli, "LLMConfig", UnconfiguredLLMConfig)

    code, out, _ = run_cli(monkeypatch, capsys, "doctor", "--require-llm")

    assert code == 0
    assert "LiteLLM configured: False" in out
    assert "LiteLLM model: not set" in out
    assert "Ready: False" in out
    assert "Missing/failed requirement(s): litellm" in out


def test_doctor_json_payload_reflects_failures_and_strict_exit(monkeypatch, capsys) -> None:
    patch_which(monkeypatch, {"git": "/usr/bin/git"})
    monkeypatch.setattr(cli, "docker_available", lambda: False)
    monkeypatch.setattr(cli, "LLMConfig", UnconfiguredLLMConfig)

    code, out, _ = run_cli(monkeypatch, capsys, "doctor", "--json", "--strict", "--require-llm")

    assert code == 2
    payload = json.loads(out)
    assert payload["readiness"] == {
        "ready": False,
        "require_llm": True,
        "failed": ["docker", "litellm"],
    }
    assert payload["git"] == {"executable": "/usr/bin/git"}
    assert payload["docker"] == {"executable": None, "daemon_available": False}
    assert payload["litellm"]["configured"] is False
    assert payload["scientific_contract"]["repository_contract_trusted"] is False


def test_doctor_suppresses_litellm_configuration_error_details(monkeypatch, capsys) -> None:
    patch_which(monkeypatch, {"git": "/usr/bin/git", "docker": "/usr/bin/docker"})
    monkeypatch.setattr(cli, "docker_available", lambda: True)
    monkeypatch.setattr(cli, "LLMConfig", BrokenLLMConfig)

    code, out, _ = run_cli(monkeypatch, capsys, "doctor")

    assert code == 0
    assert "configuration rejected" not in out
    assert "Ready: True" in out


def test_doctor_json_honors_trusted_scientific_contract_env(monkeypatch, capsys) -> None:
    patch_which(monkeypatch, {"git": "/usr/bin/git", "docker": "/usr/bin/docker"})
    monkeypatch.setattr(cli, "docker_available", lambda: True)
    monkeypatch.setattr(cli, "LLMConfig", ConfiguredLLMConfig)
    monkeypatch.setenv("VERIREPRO_TRUST_REPOSITORY_CONTRACT", "1")

    code, out, _ = run_cli(monkeypatch, capsys, "doctor", "--json")

    assert code == 0
    assert json.loads(out)["scientific_contract"]["repository_contract_trusted"] is True


def test_doctor_reports_missing_git_executable(monkeypatch, capsys) -> None:
    patch_which(monkeypatch, {"docker": "/usr/bin/docker"})
    monkeypatch.setattr(cli, "docker_available", lambda: True)
    monkeypatch.setattr(cli, "LLMConfig", ConfiguredLLMConfig)

    code, out, _ = run_cli(monkeypatch, capsys, "doctor")

    assert code == 0
    assert "Git: not found" in out
    assert "Ready: False" in out
    assert "Missing/failed requirement(s): git" in out


def test_reproduce_human_report_skips_absent_intelligence_fields(monkeypatch, capsys) -> None:
    report = full_fake_report()
    report.paper_intelligence = {"ambiguities": []}
    report.environment_plan = None
    report.artifact_comparisons = ()
    report.comparisons = ()
    monkeypatch.setattr(cli, "reproduce", lambda source, **kwargs: report)

    code, out, _ = run_cli(monkeypatch, capsys, "reproduce", "paper-x")

    assert code == 0
    assert "Ambiguities: 0" in out
    assert "Task:" not in out
    assert "Critical-field completeness" not in out
    assert "Environment:" not in out
    assert "Artifacts:" not in out
    assert "Reproducibility: failed" in out


# --- workspaces helpers --------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Simple Paper", "Simple-Paper"),
        ("my paper!", "my-paper"),
        ('a/b\\c:d*e?f"g<h>i|j', "a-b-c-d-e-f-g-h-i-j"),
        ("..dots..", "dots"),
        ("星星仓库", "artifact"),
        ("   ", "artifact"),
        ("", "artifact"),
    ],
)
def test_safe_workspace_slug_sanitizes_values(value, expected) -> None:
    assert safe_workspace_slug(value) == expected


def test_safe_workspace_slug_bounds_length() -> None:
    long_name = "x" * 200
    slug = safe_workspace_slug(long_name)
    assert len(slug) == 60
    assert slug == "x" * 60
    assert len(safe_workspace_slug("y" * 59)) == 59


def test_allocate_workspace_creates_unique_isolated_dirs(tmp_path) -> None:
    first = allocate_workspace(tmp_path / "nested", "my paper!")
    second = allocate_workspace(tmp_path / "nested", "my paper!")

    assert first.parent == tmp_path / "nested"
    assert first.is_dir()
    assert second.is_dir()
    assert first != second
    assert first.name.startswith("my-paper-")
    assert second.name.startswith("my-paper-")

    shutil.rmtree(first)
    assert not first.exists()
    assert second.exists()
    shutil.rmtree(second)


def test_allocate_workspace_fails_when_ancestor_is_a_file(tmp_path) -> None:
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(OSError):
        allocate_workspace(blocker / "ws", "some-paper")


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="permission bits are not enforced for the superuser",
)
def test_allocate_workspace_fails_on_unwritable_root(tmp_path) -> None:
    root = tmp_path / "readonly"
    root.mkdir()
    root.chmod(0o500)
    try:
        with pytest.raises(PermissionError):
            allocate_workspace(root, "some-paper")
    finally:
        root.chmod(0o755)


# --- core helpers --------------------------------------------------------------


def test_build_reproduction_plan_normalizes_reference_and_lists_stages() -> None:
    plan = build_reproduction_plan("  arXiv:2401.00001 \n")

    assert plan.paper == "arXiv:2401.00001"
    assert len(plan.stages) == 8
    assert plan.stages[0] == "resolve-paper"
    assert plan.stages[-1] == "emit-reproducibility-report"
    assert plan.to_dict() == {"paper": "arXiv:2401.00001", "stages": plan.stages}


def test_build_reproduction_plan_rejects_blank_reference() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        build_reproduction_plan("   ")


def test_blank_paper_reference_exits_with_clean_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for argv in (("plan", "   "), ("analyze", " ")):
        code, out, _err = run_cli(monkeypatch, capsys, *argv)
        assert isinstance(code, str) and "non-empty" in code
        assert out == ""
    code, out, _err = run_cli(monkeypatch, capsys, "run", "")
    assert code != 0
    assert out == ""
