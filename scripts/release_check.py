from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

BASE_REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CITATION.cff",
    "ROADMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/TRUST_MODEL.md",
    "docs/LITELLM.md",
    "docs/DATASETS.md",
    "docs/SCHEMAS.md",
    "docs/REAL_PAPER_SMOKE.md",
    "docs/REPROBENCH.md",
    "docs/PUBLISHING.md",
    "docs/PUBLIC_RELEASE_CHECKLIST.md",
    "benchmarks/real-paper-smoke.json",
    "benchmarks/reprobench-seed-suite.json",
    "scripts/run_real_paper_smoke.py",
    "scripts/run_reprobench_seed.py",
    "src/verirepro/__init__.py",
    "src/verirepro/cli.py",
    "src/verirepro/__main__.py",
    "src/verirepro/reprobench.py",
)

PUBLIC_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/litellm-smoke.yml",
    ".github/workflows/real-paper-smoke.yml",
    ".github/workflows/publish.yml",
)

_PINNED_ARXIV_SOURCE = re.compile(r"^\d{4}\.\d{4,5}v\d+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_VALID_REPROBENCH_OUTCOMES = frozenset({"success", "partial", "failure"})
_SOFT_PARTIAL_TAXONOMY = "insufficient_evidence_or_execution"
_SENSITIVE_RESULT_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "base_url",
        "endpoint",
        "headers",
        "prompt",
        "response",
        "workspace",
        "workspace_root",
    }
)
_HOST_PATH_MARKERS = ("/Users/", "/home/", "\\Users\\", "\\home\\")


def _workflow_uses_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if "uses:" in line]


def _workflow_runs_on_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if re.match(r"^\s*runs-on\s*:", line)
    ]


def _version_tuple(version: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _is_at_least(version: str, minimum: tuple[int, int, int]) -> bool:
    parsed = _version_tuple(version)
    return parsed is not None and parsed >= minimum


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative_path(value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{field} must be a non-empty relative path")
    normalized = value.replace("\\", "/")
    if (
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise ValueError(f"{field} must be a confined relative path")
    return Path(normalized)


def _json_object(path: Path, *, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"could not parse {label}: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label} must contain a JSON object")
        return None
    return payload


def _expected_real_paper_cases(evidence_version: str) -> int:
    if evidence_version.startswith("0.5."):
        return 5
    return 15


def _front_half_evidence_version(version: str) -> str:
    """Return the version whose discovery/planning evidence must certify this release.

    Front-half evidence is version-matched. An unchanged corpus digest proves the
    input set is stable, but it cannot prove a newer discovery/planning algorithm
    behaved the same. Historical evidence remains immutable under its own version.
    """
    return version


def _check_real_paper_evidence(
    root: Path,
    *,
    evidence_version: str,
    errors: list[str],
) -> None:
    expected_cases = _expected_real_paper_cases(evidence_version)
    relative = f"benchmarks/real-paper-smoke-results-{evidence_version}.json"
    path = root / relative
    if not path.is_file():
        errors.append(f"missing required public-release file: {relative}")
        return

    evidence = _json_object(path, label="real-paper release evidence", errors=errors)
    if evidence is None:
        return

    summary = evidence.get("summary") or {}
    results = evidence.get("results") or []
    if evidence.get("schema_version") != 1:
        errors.append("real-paper release evidence must declare schema_version 1")
    if evidence.get("release") != evidence_version:
        errors.append("real-paper release evidence version must match its evidence baseline")
    if summary.get("cases") != expected_cases:
        errors.append(
            f"real-paper release evidence must contain all {expected_cases} release cases"
        )
    if (
        summary.get("expected_repository_found") != expected_cases
        or summary.get("found_rate") != 1.0
    ):
        errors.append(
            f"real-paper release evidence must show {expected_cases}/{expected_cases} expected repositories found"
        )
    if summary.get("top1") != expected_cases or summary.get("top1_rate") != 1.0:
        errors.append(
            f"real-paper release evidence must show {expected_cases}/{expected_cases} expected repositories ranked top-1"
        )
    if len(results) != expected_cases or any(
        not isinstance(item, dict)
        or item.get("found") is not True
        or item.get("rank") != 1
        for item in results
    ):
        errors.append("every real-paper release evidence case must be found at rank 1")

    if not evidence_version.startswith("0.5."):
        if summary.get("source_evaluable") != expected_cases:
            errors.append("0.6+ front-half evidence must show every pinned source was evaluable")
        if summary.get("evidence_anchored") != expected_cases:
            errors.append("0.6+ front-half evidence must anchor every expected repository to paper evidence")
        for key in (
            "algorithm_found_rate",
            "algorithm_top1_rate",
            "algorithm_evidence_anchor_rate",
        ):
            if summary.get(key) != 1.0:
                errors.append(f"0.6+ front-half evidence must report {key}=1.0")
        if any(
            not isinstance(item, dict)
            or item.get("discovery_status") != "ok"
            or item.get("evidence_anchored") is not True
            or not _PINNED_ARXIV_SOURCE.fullmatch(str(item.get("source") or ""))
            for item in results
        ):
            errors.append(
                "every 0.6+ front-half evidence case must use a pinned arXiv revision and verified discovery evidence"
            )

        corpus = root / "benchmarks/real-paper-smoke.json"
        if corpus.is_file() and evidence.get("corpus_sha256") != _sha256(corpus):
            errors.append(
                "front-half evidence corpus SHA-256 must match the committed corpus exactly"
            )
        if evidence.get("corpus_revision_policy") != "explicit-arxiv-vN":
            errors.append(
                "0.6+ front-half evidence must declare the explicit-arxiv-vN revision policy"
            )

    provenance = evidence.get("provenance") or {}
    if not provenance.get("github_actions_run_id") or not provenance.get("head_sha"):
        errors.append(
            "real-paper release evidence must include GitHub Actions run/head provenance"
        )


def _check_environment_planning_evidence(
    root: Path,
    *,
    evidence_version: str,
    errors: list[str],
) -> None:
    if evidence_version.startswith("0.5."):
        return

    relative = f"benchmarks/environment-planning-results-{evidence_version}.json"
    path = root / relative
    if not path.is_file():
        errors.append(f"missing required public-release file: {relative}")
        return

    evidence = _json_object(path, label="environment-planning release evidence", errors=errors)
    if evidence is None:
        return

    summary = evidence.get("summary") or {}
    results = evidence.get("results") or []
    if evidence.get("schema_version") != 1:
        errors.append("environment-planning evidence must declare schema_version 1")
    if evidence.get("release") != evidence_version:
        errors.append(
            "environment-planning evidence version must match its evidence baseline"
        )
    if summary.get("cases") != 3:
        errors.append("environment-planning evidence must contain the bounded 3-case gate")
    statuses = summary.get("repository_inspection_status") or {}
    if statuses.get("planned") != 3:
        errors.append("environment-planning evidence must show 3/3 repositories planned")
    if len(results) != 3 or any(
        not isinstance(item, dict)
        or (item.get("repository_inspection") or {}).get("status") != "planned"
        for item in results
    ):
        errors.append("every environment-planning evidence case must have status=planned")

    corpus = root / "benchmarks/real-paper-smoke.json"
    if corpus.is_file() and evidence.get("corpus_sha256") != _sha256(corpus):
        errors.append(
            "environment-planning evidence corpus SHA-256 must match the committed corpus"
        )
    provenance = evidence.get("provenance") or {}
    if not provenance.get("github_actions_run_id") or not provenance.get("head_sha"):
        errors.append(
            "environment-planning evidence must include GitHub Actions run/head provenance"
        )


def _contains_sensitive_evidence(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _SENSITIVE_RESULT_KEYS:
                return True
            if _contains_sensitive_evidence(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_sensitive_evidence(item) for item in value)
    if isinstance(value, str):
        return any(marker in value for marker in _HOST_PATH_MARKERS)
    return False


def _check_reprobench_outcome_taxonomy(
    payload: dict[str, Any], *, task_id: str, errors: list[str]
) -> str | None:
    outcome = payload.get("outcome")
    taxonomy = payload.get("failure_taxonomy")
    if outcome not in _VALID_REPROBENCH_OUTCOMES:
        errors.append(f"ReproBench result {task_id} has invalid outcome {outcome!r}")
        return None
    if (
        not isinstance(taxonomy, list)
        or not all(isinstance(item, str) and item for item in taxonomy)
        or len(set(taxonomy)) != len(taxonomy)
    ):
        errors.append(
            f"ReproBench result {task_id} failure_taxonomy must be a unique list of non-empty strings"
        )
        return str(outcome)
    if outcome == "success" and taxonomy:
        errors.append(
            f"ReproBench result {task_id} success must not declare failure taxonomy"
        )
    elif outcome == "partial" and taxonomy != [_SOFT_PARTIAL_TAXONOMY]:
        errors.append(
            f"ReproBench result {task_id} partial must declare exactly {_SOFT_PARTIAL_TAXONOMY!r}"
        )
    elif outcome == "failure" and (
        not taxonomy or _SOFT_PARTIAL_TAXONOMY in taxonomy
    ):
        errors.append(
            f"ReproBench result {task_id} failure must declare hard failure taxonomy only"
        )
    return str(outcome)


def _check_reprobench_release_evidence(
    root: Path,
    *,
    version: str,
    errors: list[str],
) -> None:
    if not _is_at_least(version, (0, 7, 0)):
        return

    relative_dir = Path(f"benchmarks/reprobench-results-{version}")
    evidence_dir = root / relative_dir
    manifest_path = evidence_dir / "manifest.json"
    if not manifest_path.is_file():
        errors.append(
            f"missing required ReproBench release evidence: {relative_dir.as_posix()}/manifest.json"
        )
        return

    manifest = _json_object(
        manifest_path, label="ReproBench release manifest", errors=errors
    )
    if manifest is None:
        return

    if manifest.get("schema_version") != 1:
        errors.append("ReproBench release manifest must declare schema_version 1")
    if manifest.get("release") != version:
        errors.append("ReproBench release manifest release must match pyproject version")
    if manifest.get("gate_passed") is not True:
        errors.append("ReproBench release manifest must record gate_passed=true")

    suite_rel = manifest.get("suite")
    if suite_rel != "benchmarks/reprobench-seed-suite.json":
        errors.append("ReproBench release manifest must bind the canonical seed suite")
    suite_path = root / "benchmarks/reprobench-seed-suite.json"
    if suite_path.is_file():
        suite_digest = _sha256(suite_path)
        if manifest.get("suite_sha256") != suite_digest:
            errors.append(
                "ReproBench release evidence suite SHA-256 must match the committed seed suite"
            )

    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("ReproBench release manifest must include provenance")
    else:
        run_id = provenance.get("github_actions_run_id")
        head_sha = str(provenance.get("head_sha") or "")
        if not isinstance(run_id, (str, int)) or not str(run_id).isdigit():
            errors.append("ReproBench provenance must include a GitHub Actions run id")
        if not _GIT_SHA.fullmatch(head_sha):
            errors.append("ReproBench provenance head_sha must be a 40-character Git SHA")
        if provenance.get("workflow") != "VeriRepro validation":
            errors.append(
                "ReproBench provenance workflow must be 'VeriRepro validation'"
            )

    cases = manifest.get("cases")
    if not isinstance(cases, list) or not 2 <= len(cases) <= 10:
        errors.append(
            "ReproBench 0.7 release evidence must contain a bounded 2-10 case seed suite"
        )
        return

    task_ids: set[str] = set()
    result_digests: dict[str, str] = {}
    result_outcomes = {"success": 0, "partial": 0, "failure": 0}
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"ReproBench release case {index + 1} must be an object")
            continue

        task_id = case.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id in task_ids:
            errors.append(
                f"ReproBench release case {index + 1} must have a unique non-empty task_id"
            )
            continue
        task_ids.add(task_id)

        if case.get("gate_passed") is not True or case.get("gate_failures") != []:
            errors.append(f"ReproBench release case {task_id} did not pass its declared gate")

        for field, digest_field, base in (
            ("task_file", "task_sha256", root),
            ("result_file", "result_sha256", evidence_dir),
        ):
            try:
                rel = _safe_relative_path(case.get(field), field=f"{task_id}.{field}")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            path = base / rel
            try:
                path.resolve().relative_to(base.resolve())
            except ValueError:
                errors.append(f"{task_id}.{field} escapes its evidence root")
                continue
            if not path.is_file():
                errors.append(f"missing ReproBench evidence file: {path.relative_to(root)}")
                continue
            digest = _sha256(path)
            declared_digest = case.get(digest_field)
            if not isinstance(declared_digest, str) or not _SHA256.fullmatch(
                declared_digest
            ):
                errors.append(f"{task_id}.{digest_field} must be a SHA-256 digest")
            elif declared_digest != digest:
                errors.append(f"{task_id}.{digest_field} does not match committed bytes")
            if field == "result_file":
                result_digests[path.name] = digest
                payload = _json_object(
                    path, label=f"ReproBench result {task_id}", errors=errors
                )
                if payload is not None:
                    task = payload.get("task") or {}
                    agent = payload.get("agent") or {}
                    measurements = payload.get("measurements") or {}
                    if payload.get("schema_version") != 1 or payload.get("benchmark") != "reprobench":
                        errors.append(f"ReproBench result {task_id} has an unsupported schema")
                    if task.get("task_id") != task_id:
                        errors.append(f"ReproBench result {task_id} task_id mismatch")
                    if agent.get("name") != "VeriRepro" or agent.get("version") != version:
                        errors.append(
                            f"ReproBench result {task_id} must identify VeriRepro {version}"
                        )
                    outcome = _check_reprobench_outcome_taxonomy(
                        payload, task_id=task_id, errors=errors
                    )
                    if outcome in result_outcomes:
                        result_outcomes[outcome] += 1
                    if not isinstance(measurements, dict):
                        errors.append(f"ReproBench result {task_id} measurements must be an object")
                    else:
                        for telemetry_key in ("model_cost_usd", "token_usage"):
                            if telemetry_key not in measurements:
                                errors.append(
                                    f"ReproBench result {task_id} must expose {telemetry_key}"
                                )
                    if _contains_sensitive_evidence(payload):
                        errors.append(
                            f"ReproBench result {task_id} contains a forbidden host/secret-bearing field or path"
                        )

    summary_rel = manifest.get("summary_file")
    try:
        summary_path_rel = _safe_relative_path(
            summary_rel, field="ReproBench manifest summary_file"
        )
    except ValueError as exc:
        errors.append(str(exc))
        return
    summary_path = evidence_dir / summary_path_rel
    if not summary_path.is_file():
        errors.append("ReproBench release summary file is missing")
        return

    summary_digest = _sha256(summary_path)
    if manifest.get("summary_sha256") != summary_digest:
        errors.append("ReproBench release summary SHA-256 does not match committed bytes")
    summary_payload = _json_object(
        summary_path, label="ReproBench release summary", errors=errors
    )
    if summary_payload is None:
        return
    if summary_payload.get("schema_version") != 1 or summary_payload.get("benchmark") != "reprobench":
        errors.append("ReproBench release summary has an unsupported schema")
    summary = summary_payload.get("summary") or {}
    if summary.get("cases") != len(task_ids):
        errors.append("ReproBench release summary case count must match the manifest")
    expected_outcomes = {
        key: value for key, value in result_outcomes.items() if value > 0
    }
    if summary.get("outcomes") != expected_outcomes:
        errors.append(
            "ReproBench release summary outcomes must match committed result evidence"
        )
    case_count = len(task_ids)
    if case_count:
        for outcome, rate_key in (
            ("success", "success_rate"),
            ("partial", "partial_rate"),
            ("failure", "failure_rate"),
        ):
            expected_rate = result_outcomes[outcome] / case_count
            if summary.get(rate_key) != expected_rate:
                errors.append(
                    f"ReproBench release summary {rate_key} must match committed result evidence"
                )
    inputs = summary_payload.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != len(task_ids):
        errors.append("ReproBench release summary inputs must cover every manifest case")
    else:
        input_ids = {item.get("task_id") for item in inputs if isinstance(item, dict)}
        if input_ids != task_ids:
            errors.append("ReproBench release summary task ids must match the manifest")
        for item in inputs:
            if not isinstance(item, dict):
                continue
            filename = item.get("file")
            digest = item.get("sha256")
            if not isinstance(filename, str) or result_digests.get(filename) != digest:
                errors.append(
                    "ReproBench release summary input hashes must match committed result files"
                )
                break


def check_release_tree(
    root: Path = ROOT,
    *,
    require_release_evidence: bool = False,
) -> list[str]:
    errors: list[str] = []
    for relative in BASE_REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"missing required public-release file: {relative}")

    try:
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"could not parse pyproject.toml: {exc}"]

    build_system = pyproject.get("build-system") or {}
    build_requires = [str(item) for item in build_system.get("requires") or []]
    if not any(item.startswith("hatchling>=1.27") for item in build_requires):
        errors.append(
            "build-system must require hatchling>=1.27 for PEP 639 license metadata"
        )

    project = pyproject.get("project") or {}
    version = str(project.get("version") or "")
    if _version_tuple(version) is None:
        errors.append("project.version must be a stable MAJOR.MINOR.PATCH release version")
    if project.get("name") != "verirepro":
        errors.append("project.name must be 'verirepro'")
    if project.get("license") != "Apache-2.0":
        errors.append("project.license must be Apache-2.0")
    if "LICENSE" not in (project.get("license-files") or []):
        errors.append("project.license-files must include LICENSE")
    if any(
        str(item).startswith("License ::") for item in project.get("classifiers") or []
    ):
        errors.append(
            "PEP 639 license expression must not be combined with deprecated License :: classifiers"
        )

    optional = project.get("optional-dependencies") or {}
    dev_dependencies = [str(item).lower() for item in optional.get("dev") or []]
    for required in ("build", "pytest", "twine"):
        if not any(
            item == required
            or item.startswith(required + ">")
            or item.startswith(required + "=")
            for item in dev_dependencies
        ):
            errors.append(f"dev dependencies must include {required}")

    scripts = project.get("scripts") or {}
    if scripts.get("verirepro") != "verirepro.cli:main":
        errors.append(
            "preferred verirepro console script must use the public verirepro namespace"
        )
    if scripts.get("reproagent") != "reproagent.cli:main":
        errors.append("legacy reproagent console script alias is missing")
    if _is_at_least(version, (0, 7, 0)):
        if scripts.get("verirepro-reprobench") != "reproagent.reprobench_adapter:main":
            errors.append("0.7+ release must expose the verirepro-reprobench CLI")
        if (
            scripts.get("verirepro-reprobench-summary")
            != "reproagent.reprobench_summary:main"
        ):
            errors.append("0.7+ release must expose the verirepro-reprobench-summary CLI")

    targets = (
        (((pyproject.get("tool") or {}).get("hatch") or {}).get("build") or {}).get(
            "targets"
        )
        or {}
    )
    wheel_packages = (targets.get("wheel") or {}).get("packages") or []
    for package_path in ("src/verirepro", "src/reproagent"):
        if package_path not in wheel_packages:
            errors.append(f"wheel packages must include {package_path}")

    init_path = root / "src/reproagent/__init__.py"
    if init_path.is_file():
        init_text = init_path.read_text(encoding="utf-8")
        match = re.search(
            r'^__version__\s*=\s*["\']([^"\']+)["\']',
            init_text,
            flags=re.MULTILINE,
        )
        if not match:
            errors.append("could not locate reproagent.__version__")
        elif match.group(1) != version:
            errors.append(
                f"version mismatch: package={match.group(1)} pyproject={version}"
            )

    public_init_path = root / "src/verirepro/__init__.py"
    if public_init_path.is_file():
        public_init = public_init_path.read_text(encoding="utf-8")
        if "from reproagent import __version__" not in public_init:
            errors.append(
                "public verirepro namespace must expose the canonical package version"
            )
        if (
            "from reproagent import ReproductionPlan, build_reproduction_plan, reproduce"
            not in public_init
        ):
            errors.append(
                "public verirepro namespace must expose the stable public API"
            )

    citation_path = root / "CITATION.cff"
    if citation_path.is_file():
        citation = citation_path.read_text(encoding="utf-8")
        if 'title: "VeriRepro:' not in citation:
            errors.append("CITATION.cff must use the public VeriRepro title")
        if f"version: {version}" not in citation:
            errors.append("CITATION.cff version must match pyproject version")

    changelog_path = root / "CHANGELOG.md"
    if changelog_path.is_file():
        changelog = changelog_path.read_text(encoding="utf-8")
        if f"## {version}" not in changelog:
            errors.append("CHANGELOG must contain an entry for the release version")

    readme_path = root / "README.md"
    if readme_path.is_file():
        readme = readme_path.read_text(encoding="utf-8")
        if not readme.startswith("# VeriRepro"):
            errors.append("README must start with the public VeriRepro brand")
        if "PASS / FAIL / PARTIAL" not in readme and "PASS**" not in readme:
            errors.append("README must document verdict semantics")
        if "verirepro.yaml" not in readme:
            errors.append("README must document the preferred verirepro.yaml manifest name")
        if "run_real_paper_smoke.py" not in readme:
            errors.append(
                "README must document the bounded real-paper discovery smoke"
            )
        if "import verirepro" not in readme:
            errors.append("README must document the public Python import namespace")
        if _is_at_least(version, (0, 7, 0)) and "verirepro-reprobench" not in readme:
            errors.append("0.7+ README must document the ReproBench CLI")

    corpus = root / "benchmarks/real-paper-smoke.json"
    if corpus.is_file():
        corpus_payload = _json_object(
            corpus, label="real-paper smoke corpus", errors=errors
        )
        if corpus_payload is not None:
            if corpus_payload.get("schema_version") != 1:
                errors.append("real-paper smoke corpus must declare schema_version 1")
            if _is_at_least(version, (0, 6, 0)):
                cases = corpus_payload.get("cases") or []
                if len(cases) != 15:
                    errors.append(
                        "0.6+ real-paper smoke corpus must contain exactly 15 release cases"
                    )
                if any(
                    not isinstance(item, dict)
                    or not _PINNED_ARXIV_SOURCE.fullmatch(
                        str(item.get("source") or "")
                    )
                    for item in cases
                ):
                    errors.append(
                        "every 0.6+ corpus source must pin an explicit arXiv vN revision"
                    )

    if require_release_evidence:
        front_half_version = _front_half_evidence_version(version)
        _check_real_paper_evidence(
            root, evidence_version=front_half_version, errors=errors
        )
        _check_environment_planning_evidence(
            root, evidence_version=front_half_version, errors=errors
        )
        _check_reprobench_release_evidence(root, version=version, errors=errors)

    ci_path = root / ".github/workflows/ci.yml"
    if ci_path.is_file():
        ci = ci_path.read_text(encoding="utf-8")
        runs_on = _workflow_runs_on_lines(ci)
        if not runs_on or not all("ubuntu-latest" in line for line in runs_on):
            errors.append("every public CI job must run on GitHub-hosted ubuntu-latest")
        if any(
            "self-hosted" in line or "experiments" in line for line in runs_on
        ):
            errors.append(
                "public CI must not execute untrusted PR code on a self-hosted runner"
            )
        if "secrets." in ci:
            errors.append("public fork-safe CI must not reference repository secrets")
        if "pull_request:" not in ci:
            errors.append("public CI must validate pull requests")
        if "persist-credentials: false" not in ci:
            errors.append(
                "public CI checkout must not persist repository credentials"
            )

    smoke_workflows = (
        ".github/workflows/litellm-smoke.yml",
        ".github/workflows/real-paper-smoke.yml",
    )
    for workflow in smoke_workflows:
        path = root / workflow
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        runs_on = _workflow_runs_on_lines(text)
        if not runs_on or not all(
            "experiments" in line and "self-hosted" in line for line in runs_on
        ):
            errors.append(f"{workflow} must target the trusted experiments runner")
        if "paper1" in text or "paper2" in text:
            errors.append(f"{workflow} must not reference frozen paper runners")
        if "workflow_dispatch:" not in text:
            errors.append(f"{workflow} must remain maintainer-dispatched")

    for workflow in PUBLIC_WORKFLOWS:
        path = root / workflow
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for line in _workflow_uses_lines(text):
            if not re.search(r"@[0-9a-f]{40}(?:\s|$)", line):
                errors.append(
                    "public workflow action must be pinned to a 40-character "
                    f"commit SHA: {workflow}: {line}"
                )

    publish_path = root / ".github/workflows/publish.yml"
    if publish_path.is_file():
        publish = publish_path.read_text(encoding="utf-8")
        required_fragments = (
            "release:\n    types: [published]",
            "environment:\n      name: pypi",
            "id-token: write",
            "pypa/gh-action-pypi-publish@",
            "python -m twine check dist/*",
            "GITHUB_REF_NAME",
            "python scripts/release_check.py --require-release-evidence",
        )
        for fragment in required_fragments:
            if fragment not in publish:
                errors.append(
                    f"publish workflow missing release safety requirement: {fragment!r}"
                )
        forbidden = ("PYPI_API_TOKEN", "password:", "username:")
        for fragment in forbidden:
            if fragment in publish:
                errors.append(
                    "publish workflow must not contain long-lived credential input: "
                    f"{fragment!r}"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the VeriRepro public-release tree."
    )
    parser.add_argument(
        "--require-release-evidence",
        action="store_true",
        help=(
            "require version-matched front-half and ReproBench benchmark evidence with "
            "trusted GitHub Actions provenance"
        ),
    )
    args = parser.parse_args()
    errors = check_release_tree(require_release_evidence=args.require_release_evidence)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    mode = "final release" if args.require_release_evidence else "source"
    print(f"PASS: VeriRepro {mode} tree checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())