"""Hybrid retrieval with reciprocal-rank fusion."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from multi_agentic_rag.domain import RankedRetrievalResult, RetrievalResult
from multi_agentic_rag.retrieval.evidence import rank_retrieval_results
from multi_agentic_rag.retrieval.reranker import NoOpRerankingService, RerankingService


class Retriever(Protocol):
    """Retriever contract."""

    async def retrieve(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str = "default",
        version: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Retrieve results.

        Args:
            query_text: Query text supplied by the caller.
            system_name: System filter.
            kb_name: Knowledge-base filter.
            version: Optional document version filter.
            top_k: Maximum number of results expected from this retriever.

        Returns:
            Ranked retrieval results from one backend.
        """


class HybridKnowledgeRetriever:
    """Fuse BM25, vector, and graph results deterministically."""

    def __init__(
        self,
        *,
        bm25: Retriever,
        vector: Retriever | None = None,
        graph: Retriever | None = None,
        reranker: RerankingService | None = None,
        fusion_k: int = 60,
    ) -> None:
        """Initialize the hybrid retriever.

        Args:
            bm25: Required lexical retriever.
            vector: Optional vector retriever.
            graph: Optional graph expansion retriever.
            reranker: Optional final reranking service. Defaults to no-op.
            fusion_k: Reciprocal-rank-fusion constant; higher values reduce
                the effect of rank position differences.
        """

        self.bm25 = bm25
        self.vector = vector
        self.graph = graph
        self.reranker = reranker or NoOpRerankingService()
        self.fusion_k = fusion_k

    async def retrieve(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str = "default",
        version: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Retrieve and fuse results.

        Args:
            query_text: Query text passed to each configured retriever.
            system_name: System filter shared across retrievers.
            kb_name: Knowledge-base filter shared across retrievers.
            version: Optional version filter shared across retrievers.
            top_k: Maximum number of fused and reranked results to return.

        Returns:
            De-duplicated retrieval results ranked with reciprocal-rank fusion
            and optionally rescored by the configured reranker.
        """

        calls = [
            self.bm25.retrieve(
                query_text,
                system_name=system_name,
                kb_name=kb_name,
                version=version,
                top_k=top_k,
            )
        ]
        if self.vector:
            calls.append(
                self.vector.retrieve(
                    query_text,
                    system_name=system_name,
                    kb_name=kb_name,
                    version=version,
                    top_k=top_k,
                )
            )
        if self.graph:
            calls.append(
                self.graph.retrieve(
                    query_text,
                    system_name=system_name,
                    kb_name=kb_name,
                    version=version,
                    top_k=top_k,
                )
            )
        ranked_lists = list(await asyncio.gather(*calls))
        fused = self._fuse(ranked_lists)
        reranked = await self.reranker.arerank(
            query_text,
            fused[:top_k],
        )
        ranked: list[RankedRetrievalResult] = list(rank_retrieval_results(reranked))
        ranked = [
            result.model_copy(
                update={
                    "metadata": {
                        **result.metadata,
                        "final_rank": result.rank,
                        "final_score": result.score,
                    }
                }
            )
            for result in ranked
        ]
        results: list[RetrievalResult] = []
        results.extend(ranked)
        return results

    def _fuse(self, ranked_lists: list[list[RetrievalResult]]) -> list[RetrievalResult]:
        scores: dict[str, float] = {}
        best: dict[str, RetrievalResult] = {}
        sources: dict[str, set[str]] = {}
        metadata: dict[str, dict[str, Any]] = {}
        for ranked in ranked_lists:
            for rank, result in enumerate(ranked, start=1):
                scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / (
                    self.fusion_k + rank
                )
                scores[result.chunk_id] += _graph_signal_boost(result)
                current = best.get(result.chunk_id)
                if current is None or result.score > current.score:
                    best[result.chunk_id] = result
                sources.setdefault(result.chunk_id, set()).update(result.sources)
                metadata.setdefault(result.chunk_id, {}).update(result.metadata)
        for chunk_id, source_set in sources.items():
            if "graph" in source_set and source_set.intersection({"bm25", "fts", "vector"}):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 0.02
        fused = [
            best[chunk_id].model_copy(
                update={
                    "score": score,
                    "sources": sorted(sources.get(chunk_id, set())),
                    "metadata": {
                        **metadata.get(chunk_id, {}),
                        "fusion_score": score,
                        "fusion_sources": sorted(sources.get(chunk_id, set())),
                    },
                }
            )
            for chunk_id, score in scores.items()
        ]
        return sorted(fused, key=lambda item: (-item.score, item.chunk_id))


def _graph_signal_boost(result: RetrievalResult) -> float:
    if "graph" not in result.sources:
        return 0.0
    graph_score = _float_metadata(result.metadata.get("graph_score"))
    path_count = _float_metadata(result.metadata.get("graph_path_count"))
    return min(graph_score, 6.0) * 0.005 + min(path_count, 5.0) * 0.002


def _float_metadata(value: object) -> float:
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0
