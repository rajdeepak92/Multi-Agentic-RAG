"""Natural-language task routing for MARAG happy paths."""

from __future__ import annotations

from pathlib import Path

from multi_agentic_rag.agents.workflows import run_task_workflow
from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.coverage import DEFAULT_SCENARIO_COUNT
from multi_agentic_rag.models import TaskResult
from multi_agentic_rag.testing import DEFAULT_OUTPUT_DIR


def handle_task(
    user_request: str,
    *,
    system_name: str | None = None,
    version: str | None = None,
    scenario_count: int = DEFAULT_SCENARIO_COUNT,
    output_dir: str | Path | None = None,
    settings: Settings | None = None,
) -> TaskResult:
    """Route a user request to query, coverage, testcase generation, or execution."""

    settings = settings or get_settings()
    if not system_name:
        return TaskResult(
            supported=False,
            intent="missing_system",
            message="A system name is required to route MARAG tasks.",
        )
    return run_task_workflow(
        user_request,
        system_name=system_name,
        version=version,
        scenario_count=scenario_count,
        output_dir=str(output_dir or DEFAULT_OUTPUT_DIR),
        settings=settings,
    )
