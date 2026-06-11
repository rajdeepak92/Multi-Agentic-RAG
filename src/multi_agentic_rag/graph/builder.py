"""Graph construction facade."""

from __future__ import annotations

from multi_agentic_rag.models import ChunkRecord, DeltaRecord, DocumentRecord, FactRecord
from multi_agentic_rag.storage.graph_store import GraphStore


def build_basic_graph(
    graph_store: GraphStore,
    *,
    document: DocumentRecord,
    chunks: list[ChunkRecord],
    facts: list[FactRecord],
    deltas: list[DeltaRecord],
) -> None:
    """Create indexes and upsert document/chunk/fact/delta graph data."""

    graph_store.create_indexes()
    graph_store.upsert_ingestion_graph(
        document=document,
        chunks=chunks,
        facts=facts,
        deltas=deltas,
    )
