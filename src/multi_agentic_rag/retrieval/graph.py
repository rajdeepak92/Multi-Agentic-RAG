"""Neo4j graph retriever."""

from __future__ import annotations

from typing import Protocol

from multi_agentic_rag.domain import RetrievalResult


class GraphChunkRepository(Protocol):
    """Repository contract for loading chunks by IDs."""

    async def list_chunks_by_ids(
        self,
        chunk_ids: list[str],
        *,
        active_only: bool = False,
    ) -> list[RetrievalResult]:
        """Load chunks by ID.

        Args:
            chunk_ids: Chunk identifiers returned from graph traversal.
            active_only: Whether to exclude superseded chunks.

        Returns:
            Retrieval-ready chunks for IDs known to the storage backend.
        """


class GraphRepository(Protocol):
    """Graph traversal contract."""

    def related_chunk_ids(
        self,
        *,
        query_text: str,
        system_name: str,
        kb_name: str,
        version: str | None,
        active_only: bool | None,
        top_k: int,
    ) -> list[str]:
        """Return related chunk IDs.

        Args:
            query_text: Query text used to match fact or requirement nodes.
            system_name: System filter.
            kb_name: Knowledge-base filter.
            version: Optional document version filter.
            active_only: Whether to restrict graph traversal to active evidence.
            top_k: Maximum number of related chunk IDs to return.

        Returns:
            Chunk IDs selected by graph traversal.
        """


class GraphRetriever:
    """Neo4j-backed graph retriever."""

    def __init__(
        self, graph_repository: GraphRepository, chunk_repository: GraphChunkRepository
    ) -> None:
        """Initialize the graph retriever.

        Args:
            graph_repository: Backend that selects related chunk IDs from graph
                facts and requirements.
            chunk_repository: Backend that loads chunk text and metadata for
                the graph-selected IDs.
        """

        self.graph_repository = graph_repository
        self.chunk_repository = chunk_repository

    async def retrieve(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str = "default",
        version: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Retrieve graph-expanded chunks.

        Args:
            query_text: Query text used for graph-side fact matching.
            system_name: System filter.
            kb_name: Knowledge-base filter.
            version: Optional document version filter.
            top_k: Maximum number of graph-expanded chunks to return.

        Returns:
            Chunks loaded from PostgreSQL after Neo4j selects related IDs.
        """

        chunk_ids = self.graph_repository.related_chunk_ids(
            query_text=query_text,
            system_name=system_name,
            kb_name=kb_name,
            version=version,
            active_only=version is None,
            top_k=top_k,
        )
        return await self.chunk_repository.list_chunks_by_ids(
            chunk_ids,
            active_only=version is None,
        )
