"""LangGraph compilation."""

from __future__ import annotations

from typing import Any

from multi_agentic_rag.agents import nodes
from multi_agentic_rag.agents.state import AgentStateDict


def compile_graph() -> Any:
    """Compile a basic LangGraph workflow."""

    try:
        from langgraph.graph import END, StateGraph
    except Exception:  # pragma: no cover - dependency availability
        return _FallbackWorkflow()

    graph = StateGraph(AgentStateDict)
    graph.add_node("route_input", nodes.route_input)
    graph.add_node("ingest_document", nodes.ingest_document)
    graph.add_node("build_graph", nodes.build_graph)
    graph.add_node("compute_delta", nodes.compute_delta)
    graph.add_node("route_query", nodes.route_query)
    graph.add_node("retrieve_context", nodes.retrieve_context)
    graph.add_node("verify_evidence", nodes.verify_evidence)
    graph.add_node("generate_output", nodes.generate_output)

    graph.set_entry_point("route_input")
    graph.add_edge("route_input", "route_query")
    graph.add_edge("route_query", "retrieve_context")
    graph.add_edge("retrieve_context", "verify_evidence")
    graph.add_edge("verify_evidence", "generate_output")
    graph.add_edge("generate_output", END)
    return graph.compile()


class _FallbackWorkflow:
    """Simple workflow fallback when LangGraph is unavailable."""

    def invoke(self, state: AgentStateDict) -> AgentStateDict:
        for step in (
            nodes.route_input,
            nodes.route_query,
            nodes.retrieve_context,
            nodes.verify_evidence,
            nodes.generate_output,
        ):
            state = step(state)
        return state
