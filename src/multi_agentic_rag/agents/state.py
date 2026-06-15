"""Agent workflow state contracts."""

from __future__ import annotations

from typing import Any, TypedDict

from pydantic import BaseModel, Field


class AgentState(BaseModel):
    """Pydantic state contract for agentic workflows."""

    input_type: str | None = None
    user_query: str | None = None
    source_path: str | None = None
    system_name: str | None = None
    version: str | None = None
    scenario_count: int | None = None
    force_run_all: bool = False
    execution_mode: str | None = None
    output_dir: str | None = None
    intent: str | None = None
    execution_plan: dict[str, Any] | None = None
    missing_dependencies: list[str] = Field(default_factory=list)
    generated_code_paths: list[str] = Field(default_factory=list)
    test_results: list[dict[str, Any]] = Field(default_factory=list)
    next_node: str | None = None
    retry_count: int = 0
    internal_settings: Any | None = Field(default=None, alias="_settings")
    documents: list[dict[str, Any]] = Field(default_factory=list)
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_context: list[dict[str, Any]] = Field(default_factory=list)
    graph_context: list[dict[str, Any]] = Field(default_factory=list)
    delta_records: list[dict[str, Any]] = Field(default_factory=list)
    coverage_records: list[dict[str, Any]] = Field(default_factory=list)
    ingest_result: dict[str, Any] | None = None
    query_result: dict[str, Any] | None = None
    coverage_result: dict[str, Any] | None = None
    test_generation: dict[str, Any] | None = None
    test_execution: dict[str, Any] | None = None
    syntax_validation: dict[str, Any] | None = None
    sidecar_status: dict[str, Any] | None = None
    db_update_status: str | None = None
    final_validation: dict[str, Any] | None = None
    intent_decision: dict[str, Any] | None = None
    handoff_summaries: list[dict[str, Any]] = Field(default_factory=list)
    task_result: dict[str, Any] | None = None
    final_output: dict[str, Any] | None = None
    workflow_trace: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class AgentStateDict(TypedDict, total=False):
    """LangGraph-compatible state shape."""

    input_type: str | None
    user_query: str | None
    source_path: str | None
    system_name: str | None
    version: str | None
    scenario_count: int | None
    force_run_all: bool
    execution_mode: str | None
    output_dir: str | None
    intent: str | None
    execution_plan: dict[str, Any] | None
    missing_dependencies: list[str]
    generated_code_paths: list[str]
    test_results: list[dict[str, Any]]
    next_node: str | None
    retry_count: int
    _settings: Any | None
    documents: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    retrieved_context: list[dict[str, Any]]
    graph_context: list[dict[str, Any]]
    delta_records: list[dict[str, Any]]
    coverage_records: list[dict[str, Any]]
    ingest_result: dict[str, Any] | None
    query_result: dict[str, Any] | None
    coverage_result: dict[str, Any] | None
    test_generation: dict[str, Any] | None
    test_execution: dict[str, Any] | None
    syntax_validation: dict[str, Any] | None
    sidecar_status: dict[str, Any] | None
    db_update_status: str | None
    final_validation: dict[str, Any] | None
    intent_decision: dict[str, Any] | None
    handoff_summaries: list[dict[str, Any]]
    task_result: dict[str, Any] | None
    final_output: dict[str, Any] | None
    workflow_trace: list[dict[str, Any]]
    warnings: list[str]
    errors: list[str]
