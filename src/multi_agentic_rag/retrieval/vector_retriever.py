"""Vector retrieval over ChromaDB."""

from __future__ import annotations

from multi_agentic_rag.models import DocumentStatus
from multi_agentic_rag.storage.chroma_store import ChromaVectorStore


class VectorRetriever:
    """Thin retriever wrapper with status/version filters."""

    def __init__(self, vector_store: ChromaVectorStore) -> None:
        self.vector_store = vector_store

    def retrieve_current(self, query: str, *, system_name: str, top_k: int = 5):
        return self.vector_store.query(
            query,
            filters={"system_name": system_name, "status": DocumentStatus.ACTIVE.value},
            top_k=top_k,
        )

    def retrieve_historical(
        self,
        query: str,
        *,
        system_name: str,
        version: str | None = None,
        top_k: int = 5,
    ):
        filters = {"system_name": system_name, "status": DocumentStatus.SUPERSEDED.value}
        if version:
            filters["version"] = version
        return self.vector_store.query(query, filters=filters, top_k=top_k)
