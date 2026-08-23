from __future__ import annotations

import json

from .models import ReproductionReport


def _clip(text: str, limit: int = 180) -> str:
    value = " ".join(text.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _cell(value: object) -> str:
    return _clip(str(value)).replace("|", "\\|")


def render_markdown(report: ReproductionReport) -> str:
    lines = [
        "# VeriRepro Reproducibility Report",
        "",
        f"- **Source:** {report.source}",
        f"- **Repository:** {report.repository or 'not found'}",
        f"- **Status:** {report.status}",
        f"- **Detected stack:** {', '.join(report.stacks) if report.stacks else 'unknown'}",
        "",
        "## Pipeline",
        "",
    ]
    for stage in report.stages:
        symbol = {"passed": "✓", "failed": "✗", "skipped": "○"}.get(stage.status, "•")
        lines.append(f"- {symbol} **{stage.name}** — {stage.detail}")

    intelligence = report.paper_intelligence
    if intelligence:
        lines.extend(["", "## Paper intelligence", ""])
        if intelligence.get("task"):
            lines.append(f"**Task:** {intelligence['task']}")
            lines.append("")
        lines.append(f"**Model:** `{intelligence.get('model', 'unknown')}`")
        if "reproduction_completeness" in intelligence:
            lines.append(
                f"**Critical-field completeness:** {float(intelligence['reproduction_completeness']):.0%}"
            )
        lines.extend(["", "### Evidence anchors", ""])
        evidence = intelligence.get("evidence") or []
        if evidence:
            lines.extend([
                "| Field | Value | Page | Verification | Evidence |",
                "|---|---|---:|:---:|---|",
            ])
            for item in evidence:
                page = item.get("page") or "—"
                lines.append(
                    f"| {_cell(item.get('field', 'unknown'))} | {_cell(item.get('value', ''))} | {page} | "
                    f"{str(item.get('verification', 'unverified')).upper()} | {_cell(item.get('quote', ''))} |"
                )
        else:
            lines.append("No structured evidence claims were returned.")

        lines.extend(["", "### Ambiguity audit", ""])
        ambiguities = intelligence.get("ambiguities") or []
        if ambiguities:
            lines.extend([
                "| Severity | Field | Issue | Recommended action |",
                "|:---:|---|---|---|",
            ])
            for item in ambiguities:
                lines.append(
                    f"| {str(item.get('severity', 'medium')).upper()} | {_cell(item.get('field', 'unknown'))} | "
                    f"{_cell(item.get('issue', ''))} | {_cell(item.get('recommendation', ''))} |"
                )
        else:
            lines.append("No reproduction-critical ambiguities were identified by the configured model.")

    discovery = report.artifact_discovery
    if discovery:
        lines.extend(["", "## Artifact discovery", ""])
        candidates = discovery.get("repository_candidates") or []
        if candidates:
            lines.extend([
                "| Rank | Repository | Score | Occurrences | Evidence signals |",
                "|---:|---|---:|---:|---|",
            ])
            for rank, item in enumerate(candidates, start=1):
                reasons = ", ".join(item.get("reasons") or []) or "frequency"
                lines.append(
                    f"| {rank} | {_cell(item.get('url', ''))} | {item.get('score', 0)} | "
                    f"{item.get('occurrences', 0)} | {_cell(reasons)} |"
                )
        else:
            lines.append("No GitHub repository candidates were discovered.")

    repository_plan = report.repository_plan
    if repository_plan:
        lines.extend(["", "## Repository execution plan", ""])
        lines.append(f"- **Verification:** {str(repository_plan.get('verification', 'unverified')).upper()}")
        lines.append(f"- **Entrypoint:** `{repository_plan.get('entrypoint') or 'none'}`")
        lines.append(f"- **Command:** `{repository_plan.get('command') or 'rejected / unavailable'}`")
        lines.append(f"- **Evidence file:** `{repository_plan.get('evidence_file') or 'none'}`")
        lines.append(f"- **Rationale:** {_clip(str(repository_plan.get('rationale') or ''))}")
        if repository_plan.get("evidence_quote"):
            lines.append(f"- **Repository evidence:** {_clip(str(repository_plan['evidence_quote']))}")

    plan = report.environment_plan
    if plan:
        lines.extend(["", "## Environment provenance", ""])
        lines.append(f"- **Resolved Python:** `{plan.get('python_version', 'unknown')}`")
        lines.append(f"- **Python source:** `{plan.get('python_source', 'unknown')}`")
        lines.append(f"- **Repository requirement:** `{plan.get('python_requirement') or 'not specified'}`")
        lines.append(f"- **Dependency strategy:** `{plan.get('dependency_strategy', 'none')}`")
        lines.append(f"- **Repository commit:** `{plan.get('commit_sha') or 'unknown'}`")
        lines.append(f"- **Repository fingerprint:** `{plan.get('repository_fingerprint') or 'unknown'}`")
        lines.append(f"- **Environment fingerprint:** `{plan.get('environment_fingerprint') or 'unknown'}`")
        lines.append(f"- **Reproducibility grade:** **{str(plan.get('reproducibility_grade', 'weak')).upper()}**")
        lines.append(f"- **GPU likely:** `{bool(plan.get('gpu_likely'))}`")
        warnings = plan.get("warnings") or []
        if warnings:
            lines.extend(["", "### Environment warnings", ""])
            lines.extend(f"- {_cell(warning)}" for warning in warnings)

    lines.extend(["", "## Reproduced artifacts", ""])
    if report.artifact_comparisons:
        lines.extend([
            "| Artifact | Type | Score | Threshold | Result | Detail |",
            "|---|:---:|---:|---:|:---:|---|",
        ])
        for item in report.artifact_comparisons:
            lines.append(
                f"| {_cell(item.name)} | {item.kind} | {item.score:.4f} | {item.threshold:.4f} | "
                f"{'PASS' if item.passed else 'FAIL'} | {_cell(item.detail)} |"
            )
    else:
        lines.append("No declared figure/table/file comparisons were evaluated.")

    if report.output_artifacts:
        lines.extend(["", "### Output inventory", ""])
        lines.extend([
            "| Path | Type | Bytes | SHA-256 |",
            "|---|:---:|---:|---|",
        ])
        for item in report.output_artifacts:
            lines.append(
                f"| `{_cell(item.path)}` | {item.kind} | {item.size_bytes} | `{item.sha256[:16]}…` |"
            )

    lines.extend(["", "## Metrics", ""])
    if report.comparisons:
        lines.extend([
            "| Metric | Paper | Reproduced | Difference | Tolerance | Result |",
            "|---|---:|---:|---:|---:|:---:|",
        ])
        for item in report.comparisons:
            lines.append(
                f"| {item.name} | {item.paper:.6g} | {item.reproduced:.6g} | "
                f"{item.difference:+.6g} | {item.tolerance:.6g} | "
                f"{'PASS' if item.passed else 'FAIL'} |"
            )
    else:
        lines.append("No comparable metrics were produced.")
    lines.append("")
    return "\n".join(lines)


def write_report(report: ReproductionReport) -> ReproductionReport:
    report.workspace.mkdir(parents=True, exist_ok=True)
    json_path = report.workspace / "report.json"
    markdown_path = report.workspace / "report.md"
    report.report_json = json_path
    report.report_markdown = markdown_path
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return report
