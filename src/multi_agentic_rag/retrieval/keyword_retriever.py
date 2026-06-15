"""SQLite FTS5 keyword retrieval."""

from __future__ import annotations

from multi_agentic_rag.models import DocumentStatus
from multi_agentic_rag.storage.registry import Registry


class KeywordRetriever:
    """BM25 keyword retriever for IDs, protocols, endpoints, and exact terms."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def retrieve(
        self,
        query: str,
        *,
        system_name: str | None = None,
        version: str | None = None,
        status: DocumentStatus | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        return self.registry.search_chunks(
            query,
            system_name=system_name,
            version=version,
            status=status,
            top_k=top_k,
        )
