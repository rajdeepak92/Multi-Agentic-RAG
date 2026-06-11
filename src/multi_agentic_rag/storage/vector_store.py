"""Vector store interface."""

from __future__ import annotations

from typing import Any, Protocol

from multi_agentic_rag.models import ChunkRecord


class VectorStore(Protocol):
    """Minimal vector store contract used by ingestion and retrieval."""

    def index_chunks(self, chunks: list[ChunkRecord]) -> None: ...

    def query(
        self,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]: ...
