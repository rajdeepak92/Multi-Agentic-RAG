import pytest

from multi_agentic_rag.config import get_settings
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore
from multi_agentic_rag.workflows import run_graph_check


def test_live_neo4j_graph_check_when_reachable() -> None:
    store = Neo4jGraphStore(get_settings())
    available, message = store.check_connection()
    if not available:
        store.close()
        pytest.skip(f"Neo4j is not reachable: {message}")

    result = run_graph_check(graph_store=store)

    assert result.success
