"""Knowledge graph store interface."""

from __future__ import annotations

from typing import Protocol

from multi_agentic_rag.models import ChunkRecord, DeltaRecord, DocumentRecord, FactRecord


class GraphStore(Protocol):
    """Minimal graph database contract."""

    def check_connection(self) -> tuple[bool, str]: ...

    def create_indexes(self) -> None: ...

    def upsert_ingestion_graph(
        self,
        *,
        document: DocumentRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
    ) -> None: ...
