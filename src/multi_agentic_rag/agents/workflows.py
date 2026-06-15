"""Workflow entry points."""

from __future__ import annotations

from typing import Any

from multi_agentic_rag.agents.graph import compile_graph
from multi_agentic_rag.config import Settings
from multi_agentic_rag.coverage import DEFAULT_SCENARIO_COUNT
from multi_agentic_rag.models import TaskResult


def compile_basic_workflow() -> Any:
    """Return the Phase 1 LangGraph workflow."""

    return compile_graph()


def run_task_workflow(
    user_request: str,
    *,
    system_name: str | None = None,
    version: str | None = None,
    scenario_count: int = DEFAULT_SCENARIO_COUNT,
    execution_mode: str | None = None,
    output_dir: str | None = None,
    settings: Settings | None = None,
) -> TaskResult:
    """Run a natural-language MARAG request through the agent workflow."""

    workflow = compile_basic_workflow()
    state = {
        "user_query": user_request,
        "system_name": system_name,
        "version": version,
        "scenario_count": scenario_count,
        "execution_mode": execution_mode,
        "output_dir": output_dir,
        "_settings": settings,
    }
    result_state = workflow.invoke(state)
    task_result = result_state.get("task_result")
    if task_result:
        return TaskResult.model_validate(task_result)
    errors = result_state.get("errors") or ["Workflow completed without a task result."]
    return TaskResult(
        supported=False,
        intent=result_state.get("input_type") or "unknown",
        message="; ".join(errors),
        warnings=errors,
    )
