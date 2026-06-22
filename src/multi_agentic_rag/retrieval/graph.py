"""Neo4j graph retriever."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Protocol

from multi_agentic_rag.domain import GraphMatch, RetrievalResult


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

    def related_chunk_matches(
        self,
        *,
        query_text: str,
        system_name: str,
        kb_name: str,
        version: str | None,
        active_only: bool | None,
        top_k: int,
    ) -> list[GraphMatch]:
        """Return graph traversal matches with scores and explainable paths."""

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

        matches = self._related_chunk_matches(
            query_text=query_text,
            system_name=system_name,
            kb_name=kb_name,
            version=version,
            top_k=top_k,
        )
        ordered_chunk_ids = _rank_graph_chunk_ids(matches, top_k=top_k)
        hydrated = await self.chunk_repository.list_chunks_by_ids(
            ordered_chunk_ids,
            active_only=version is None,
        )
        return [_with_graph_metadata(result, matches) for result in hydrated]

    def _related_chunk_matches(
        self,
        *,
        query_text: str,
        system_name: str,
        kb_name: str,
        version: str | None,
        top_k: int,
    ) -> list[GraphMatch]:
        if hasattr(self.graph_repository, "related_chunk_matches"):
            return self.graph_repository.related_chunk_matches(
                query_text=query_text,
                system_name=system_name,
                kb_name=kb_name,
                version=version,
                active_only=version is None,
                top_k=top_k,
            )
        return [
            GraphMatch(
                chunk_id=chunk_id,
                score=1.0,
                reason="legacy graph chunk match",
                path=[f"Chunk:{chunk_id}"],
                matched_terms=[],
            )
            for chunk_id in self.graph_repository.related_chunk_ids(
                query_text=query_text,
                system_name=system_name,
                kb_name=kb_name,
                version=version,
                active_only=version is None,
                top_k=top_k,
            )
        ]


def _rank_graph_chunk_ids(matches: list[GraphMatch], *, top_k: int) -> list[str]:
    matches = _deduplicate_matches(matches)
    scores: dict[str, float] = defaultdict(float)
    first_seen: dict[str, int] = {}
    for index, match in enumerate(matches):
        scores[match.chunk_id] += match.score
        first_seen.setdefault(match.chunk_id, index)
    return [
        chunk_id
        for chunk_id, _ in sorted(
            scores.items(),
            key=lambda item: (-item[1], first_seen[item[0]], item[0]),
        )[:top_k]
    ]


def _with_graph_metadata(
    result: RetrievalResult,
    matches: list[GraphMatch],
) -> RetrievalResult:
    chunk_matches = _deduplicate_matches(
        [match for match in matches if match.chunk_id == result.chunk_id]
    )
    if not chunk_matches:
        return result
    graph_matches = [match.model_dump(mode="json") for match in chunk_matches]
    graph_score = sum(match.score for match in chunk_matches)
    matched_terms = sorted({term for match in chunk_matches for term in match.matched_terms})
    graph_paths = [match.path for match in chunk_matches if match.path]
    metadata: dict[str, Any] = {
        **result.metadata,
        "graph_score": graph_score,
        "graph_path_count": len(graph_paths),
        "graph_paths": graph_paths,
        "graph_reasons": [match.reason for match in chunk_matches],
        "graph_matched_terms": matched_terms,
        "graph_matches": graph_matches,
    }
    sources = sorted({*result.sources, "graph"})
    return result.model_copy(
        update={
            "score": graph_score,
            "sources": sources,
            "metadata": metadata,
        }
    )


def _deduplicate_matches(matches: list[GraphMatch]) -> list[GraphMatch]:
    merged: dict[tuple[str, str, tuple[str, ...]], GraphMatch] = {}
    for match in matches:
        key = (match.chunk_id, match.reason, tuple(match.path))
        existing = merged.get(key)
        if existing is None:
            merged[key] = match
            continue
        merged_terms = sorted({*existing.matched_terms, *match.matched_terms})
        merged[key] = existing.model_copy(
            update={
                "score": max(existing.score, match.score),
                "matched_terms": merged_terms,
            }
        )
    return list(merged.values())
