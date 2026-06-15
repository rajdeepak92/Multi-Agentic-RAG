"""LangGraph compilation."""

from __future__ import annotations

from typing import Any

from multi_agentic_rag.agents import nodes
from multi_agentic_rag.agents.state import AgentStateDict


def compile_graph() -> Any:
    """Compile the fine-grained MARAG agent workflow."""

    try:
        from langgraph.graph import END, StateGraph
    except Exception:  # pragma: no cover - dependency availability
        return _FallbackWorkflow()

    graph = StateGraph(AgentStateDict)
    graph.add_node("route_input", nodes.route_input)
    graph.add_node("document_resolver", nodes.document_resolver)
    graph.add_node("ingest_document", nodes.ingest_document)
    graph.add_node("build_graph", nodes.build_graph)
    graph.add_node("version_delta", nodes.version_delta)
    graph.add_node("route_query", nodes.route_query)
    graph.add_node("retrieve_context", nodes.retrieve_context)
    graph.add_node("verify_evidence", nodes.verify_evidence)
    graph.add_node("domain_analyzer", nodes.domain_analyzer)
    graph.add_node("dependency_audit", nodes.dependency_audit)
    graph.add_node("test_harness", nodes.test_harness)
    graph.add_node("test_writer", nodes.test_writer)
    graph.add_node("robot_mapping", nodes.robot_mapping)
    graph.add_node("syntax_validation", nodes.syntax_validation)
    graph.add_node("test_execution", nodes.test_execution)
    graph.add_node("failure_classifier", nodes.failure_classifier)
    graph.add_node("json_sidecar", nodes.json_sidecar)
    graph.add_node("database_update", nodes.database_update)
    graph.add_node("report_generator", nodes.report_generator)
    graph.add_node("final_router_validation", nodes.final_router_validation)
    graph.add_node("build_task_result", nodes.build_task_result)

    graph.set_entry_point("route_input")
    graph.add_edge("route_input", "document_resolver")
    graph.add_edge("document_resolver", "ingest_document")
    graph.add_edge("ingest_document", "build_graph")
    graph.add_edge("build_graph", "version_delta")
    graph.add_edge("version_delta", "route_query")
    graph.add_edge("route_query", "retrieve_context")
    graph.add_edge("retrieve_context", "verify_evidence")
    graph.add_conditional_edges(
        "verify_evidence",
        nodes.route_after_evidence,
        {
            "continue": "domain_analyzer",
            "final_report": "report_generator",
        },
    )
    graph.add_edge("domain_analyzer", "dependency_audit")
    graph.add_conditional_edges(
        "dependency_audit",
        nodes.route_after_dependency_audit,
        {
            "continue": "test_harness",
            "blocked": "report_generator",
        },
    )
    graph.add_edge("test_harness", "test_writer")
    graph.add_edge("test_writer", "robot_mapping")
    graph.add_edge("robot_mapping", "syntax_validation")
    graph.add_conditional_edges(
        "syntax_validation",
        nodes.route_after_syntax_validation,
        {
            "continue": "test_execution",
            "retry": "test_writer",
        },
    )
    graph.add_conditional_edges(
        "test_execution",
        nodes.route_after_execution,
        {
            "continue": "failure_classifier",
            "retry": "test_execution",
        },
    )
    graph.add_edge("failure_classifier", "json_sidecar")
    graph.add_edge("json_sidecar", "database_update")
    graph.add_edge("database_update", "report_generator")
    graph.add_edge("report_generator", "final_router_validation")
    graph.add_edge("final_router_validation", "build_task_result")
    graph.add_edge("build_task_result", END)
    return graph.compile()


class _FallbackWorkflow:
    """Simple workflow fallback when LangGraph is unavailable."""

    def invoke(self, state: AgentStateDict) -> AgentStateDict:
        for step in (
            nodes.route_input,
            nodes.document_resolver,
            nodes.ingest_document,
            nodes.build_graph,
            nodes.version_delta,
            nodes.route_query,
            nodes.retrieve_context,
            nodes.verify_evidence,
            nodes.domain_analyzer,
            nodes.dependency_audit,
            nodes.test_harness,
            nodes.test_writer,
            nodes.robot_mapping,
            nodes.syntax_validation,
            nodes.test_execution,
            nodes.failure_classifier,
            nodes.json_sidecar,
            nodes.database_update,
            nodes.report_generator,
            nodes.final_router_validation,
            nodes.build_task_result,
        ):
            state = step(state)
        return state
