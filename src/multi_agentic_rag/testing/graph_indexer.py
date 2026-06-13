"""Best-effort Neo4j indexing for generated automation traceability."""

from __future__ import annotations

from multi_agentic_rag.config import Settings
from multi_agentic_rag.models import (
    CoverageRecord,
    GeneratedTestFileRecord,
    TestRunResultRecord,
)
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore


def index_generated_test_graph(
    *,
    settings: Settings,
    test_file: GeneratedTestFileRecord,
    coverage_records: list[CoverageRecord],
) -> str | None:
    """Mirror generated test and coverage lineage to Neo4j when configured."""

    if not settings.neo4j_uri and not settings.graphrag_required:
        return None
    graph_store = Neo4jGraphStore(settings)
    available, message = graph_store.check_connection()
    if not available:
        graph_store.close()
        return f"Neo4j generated-test graph indexing skipped: {message}"
    try:
        graph_store.create_indexes()
        graph_store.upsert_generated_test_graph(
            test_file=test_file,
            coverage_records=coverage_records,
        )
    except Exception as exc:  # pragma: no cover - depends on local Neo4j
        return f"Neo4j generated-test graph indexing failed: {exc}"
    finally:
        graph_store.close()
    return None


def index_test_run_graph(
    *,
    settings: Settings,
    result: TestRunResultRecord,
    test_file: GeneratedTestFileRecord | None,
) -> str | None:
    """Mirror generated test execution status to Neo4j when configured."""

    if not settings.neo4j_uri and not settings.graphrag_required:
        return None
    graph_store = Neo4jGraphStore(settings)
    available, message = graph_store.check_connection()
    if not available:
        graph_store.close()
        return f"Neo4j test-run graph indexing skipped: {message}"
    try:
        graph_store.create_indexes()
        graph_store.upsert_test_run_graph(result=result, test_file=test_file)
    except Exception as exc:  # pragma: no cover - depends on local Neo4j
        return f"Neo4j test-run graph indexing failed: {exc}"
    finally:
        graph_store.close()
    return None
