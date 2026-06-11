"""Planned MCP tools.

These functions are placeholders and intentionally do not start an MCP runtime.
Future implementations should delegate to the same services used by FastAPI.
"""


def ingest_document() -> None:
    """Future MCP tool: ingest a versioned engineering document."""
    raise NotImplementedError("MCP is disabled in Phase 1.")


def query_current_truth() -> None:
    """Future MCP tool: answer from active version evidence only."""
    raise NotImplementedError("MCP is disabled in Phase 1.")


def query_historical_truth() -> None:
    """Future MCP tool: answer from superseded historical evidence."""
    raise NotImplementedError("MCP is disabled in Phase 1.")


def compute_delta() -> None:
    """Future MCP tool: compute or retrieve deterministic version deltas."""
    raise NotImplementedError("MCP is disabled in Phase 1.")


def generate_coverage() -> None:
    """Future MCP tool: generate requirement-linked coverage records."""
    raise NotImplementedError("MCP is disabled in Phase 1.")


def inspect_graph() -> None:
    """Future MCP tool: inspect graph lineage and relationships."""
    raise NotImplementedError("MCP is disabled in Phase 1.")
