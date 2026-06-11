"""Small testable workflow nodes."""

from __future__ import annotations

from multi_agentic_rag.agents.state import AgentStateDict
from multi_agentic_rag.retrieval.intent import detect_intent


def route_input(state: AgentStateDict) -> AgentStateDict:
    """Route initial input into document ingestion or query flow."""

    input_type = state.get("input_type")
    if not input_type:
        state["input_type"] = "query" if state.get("user_query") else "unknown"
    return state


def ingest_document(state: AgentStateDict) -> AgentStateDict:
    """Placeholder ingestion node."""

    return state


def build_graph(state: AgentStateDict) -> AgentStateDict:
    """Placeholder graph-build node."""

    return state


def compute_delta(state: AgentStateDict) -> AgentStateDict:
    """Placeholder delta node."""

    return state


def route_query(state: AgentStateDict) -> AgentStateDict:
    """Attach deterministic query intent."""

    query = state.get("user_query") or ""
    state["input_type"] = detect_intent(query).value
    return state


def retrieve_context(state: AgentStateDict) -> AgentStateDict:
    """Placeholder retrieval node."""

    state.setdefault("retrieved_context", [])
    return state


def verify_evidence(state: AgentStateDict) -> AgentStateDict:
    """Ensure final generation has evidence context available."""

    if not state.get("retrieved_context") and not state.get("graph_context"):
        state.setdefault("errors", []).append("No evidence available for output generation.")
    return state


def generate_output(state: AgentStateDict) -> AgentStateDict:
    """Create a deterministic placeholder output."""

    if state.get("errors"):
        state["final_output"] = {"supported": False, "errors": state["errors"]}
    else:
        state["final_output"] = {"supported": True}
    return state
