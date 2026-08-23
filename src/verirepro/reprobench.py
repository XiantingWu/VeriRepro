"""Public ReproBench JSON/process integration for VeriRepro.

This module intentionally depends only on VeriRepro internals. It does not
import sibling ReproBench source code; interoperability happens through
versioned task/result/summary JSON contracts.
"""

from reproagent.reprobench_adapter import (
    REPROBENCH_RESULT_SCHEMA_VERSION,
    REPROBENCH_TASK_SCHEMA_VERSION,
    ReproBenchContractError,
    ReproBenchResult,
    ReproBenchTask,
    build_reprobench_result,
    load_reprobench_task,
    parse_reprobench_task,
    run_reprobench_task,
    write_reprobench_result,
)
from reproagent.reprobench_summary import (
    REPROBENCH_SUMMARY_SCHEMA_VERSION,
    ReproBenchSummaryError,
    summarize_reprobench_results,
    write_reprobench_summary,
)

__all__ = [
    "REPROBENCH_RESULT_SCHEMA_VERSION",
    "REPROBENCH_SUMMARY_SCHEMA_VERSION",
    "REPROBENCH_TASK_SCHEMA_VERSION",
    "ReproBenchContractError",
    "ReproBenchResult",
    "ReproBenchSummaryError",
    "ReproBenchTask",
    "build_reprobench_result",
    "load_reprobench_task",
    "parse_reprobench_task",
    "run_reprobench_task",
    "summarize_reprobench_results",
    "write_reprobench_result",
    "write_reprobench_summary",
]
