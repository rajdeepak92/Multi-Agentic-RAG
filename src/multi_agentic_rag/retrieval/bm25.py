"""PostgreSQL lexical full-text retriever."""

from __future__ import annotations

from typing import Protocol

from multi_agentic_rag.domain import RetrievalResult


class BM25Repository(Protocol):
    """Repository contract used by lexical retrieval."""

    async def search_chunks(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str,
        version: str | None = None,
        active_only: bool | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Search chunks with a lexical backend.

        Args:
            query_text: Query string for the lexical backend.
            system_name: System filter.
            kb_name: Knowledge-base filter.
            version: Optional document version filter.
            active_only: Whether to restrict results to active chunks.
            top_k: Maximum number of ranked chunks to return.

        Returns:
            Ranked lexical retrieval results.
        """


class BM25Retriever:
    """PostgreSQL lexical retriever."""

    def __init__(self, repository: BM25Repository) -> None:
        """Initialize the BM25 retriever.

        Args:
            repository: Backend repository that implements PostgreSQL lexical
                chunk search.
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
        """Retrieve PostgreSQL lexical results.

        Args:
            query_text: User query to search with the configured PostgreSQL
                lexical backend.
            system_name: System filter.
            kb_name: Knowledge-base filter.
            version: Optional document version filter.
            top_k: Maximum number of ranked chunks to return.

        Returns:
            Ranked lexical results from the repository.
        """

        return await self.repository.search_chunks(
            query_text,
            system_name=system_name,
            kb_name=kb_name,
            version=version,
            active_only=version is None,
            top_k=top_k,
        )
