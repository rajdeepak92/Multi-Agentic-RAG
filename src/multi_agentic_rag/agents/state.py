"""Agent workflow state contracts."""

from __future__ import annotations

from typing import Any, TypedDict

from pydantic import BaseModel, Field


class AgentState(BaseModel):
    """Pydantic state contract for agentic workflows."""

    input_type: str | None = None
    user_query: str | None = None
    system_name: str | None = None
    version: str | None = None
    documents: list[dict[str, Any]] = Field(default_factory=list)
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_context: list[dict[str, Any]] = Field(default_factory=list)
    graph_context: list[dict[str, Any]] = Field(default_factory=list)
    delta_records: list[dict[str, Any]] = Field(default_factory=list)
    coverage_records: list[dict[str, Any]] = Field(default_factory=list)
    final_output: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)


class AgentStateDict(TypedDict, total=False):
    """LangGraph-compatible state shape."""

    input_type: str | None
    user_query: str | None
    system_name: str | None
    version: str | None
    documents: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    retrieved_context: list[dict[str, Any]]
    graph_context: list[dict[str, Any]]
    delta_records: list[dict[str, Any]]
    coverage_records: list[dict[str, Any]]
    final_output: dict[str, Any] | None
    errors: list[str]
