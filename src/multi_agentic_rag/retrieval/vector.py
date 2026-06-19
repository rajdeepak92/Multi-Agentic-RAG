"""Vector retriever."""

from __future__ import annotations

from typing import Protocol

from multi_agentic_rag.domain import RetrievalResult


class VectorRepository(Protocol):
    """Vector repository contract."""

    def query(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str,
        version: str | None = None,
        active_only: bool | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Query vector store.

        Args:
            query_text: Query text to embed.
            system_name: System filter.
            kb_name: Knowledge-base filter.
            version: Optional document version filter.
            active_only: Whether to restrict results to active chunks.
            top_k: Maximum number of vector results to return.

        Returns:
            Ranked vector retrieval results.
        """


class VectorRetriever:
    """Chroma-backed vector retriever."""

    def __init__(self, repository: VectorRepository) -> None:
        """Initialize the vector retriever.

        Args:
            repository: Backend that embeds the query and searches the vector
                store.
        """

        self.repository = repository

    async def retrieve(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str = "default",
        version: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Retrieve vector results.

        Args:
            query_text: User query to embed and search.
            system_name: System filter.
            kb_name: Knowledge-base filter.
            version: Optional document version filter.
            top_k: Maximum number of vector results to return.

        Returns:
            Ranked results from the configured vector repository.
        """

        return self.repository.query(
            query_text,
            system_name=system_name,
            kb_name=kb_name,
            version=version,
            active_only=version is None,
            top_k=top_k,
        )
