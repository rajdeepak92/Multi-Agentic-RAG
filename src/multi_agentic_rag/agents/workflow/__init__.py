"""Workflow agent public layer.

This package intentionally re-exports the existing sibling ``workflow.py`` module for one
compatibility window. It avoids moving the proven LangGraph implementation while exposing
the planned layer path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_legacy_path = Path(__file__).resolve().parent.parent / "workflow.py"
_spec = importlib.util.spec_from_file_location(
    "multi_agentic_rag.agents._workflow_legacy",
    _legacy_path,
)
if _spec is None or _spec.loader is None:  # pragma: no cover - importlib guard
    raise ImportError(f"Could not load workflow module from {_legacy_path}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

FlowValidatorAgent = _module.FlowValidatorAgent
IntentRouterAgent = _module.IntentRouterAgent
LangGraphWorkflowRunner = _module.LangGraphWorkflowRunner
WorkflowPlannerAgent = _module.WorkflowPlannerAgent
default_workflow_plan = _module.default_workflow_plan

__all__ = [
    "FlowValidatorAgent",
    "IntentRouterAgent",
    "LangGraphWorkflowRunner",
    "WorkflowPlannerAgent",
    "default_workflow_plan",
]
