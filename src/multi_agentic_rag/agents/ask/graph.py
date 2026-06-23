"""Internal compiled ask workflow facade."""

from __future__ import annotations

from typing import Any, cast

from multi_agentic_rag.domain import AgentRunResult, TaskIntent


async def run_ask_graph(
    answer_agent: Any,
    intent: TaskIntent,
    *,
    question: str,
    top_k: int | None = None,
) -> AgentRunResult:
    """Run the internal ask workflow.

    This wrapper is intentionally thin for now: it preserves the public
    ``AgentRetrieveAnswer`` composition point while giving the CLI and workflow
    runner a stable place for future retrieval-lineage/evidence-pack nodes.
    """

    result = await answer_agent._run_direct(intent, question=question, top_k=top_k)
    return cast(AgentRunResult, result)
