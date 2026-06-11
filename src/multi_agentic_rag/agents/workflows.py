"""Workflow entry points."""

from __future__ import annotations

from typing import Any

from multi_agentic_rag.agents.graph import compile_graph


def compile_basic_workflow() -> Any:
    """Return the Phase 1 LangGraph workflow."""

    return compile_graph()
