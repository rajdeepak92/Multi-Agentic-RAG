from __future__ import annotations

import asyncio

import multi_agentic_rag.retrieval.reranker as reranker_module
from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import RetrievalResult
from multi_agentic_rag.retrieval import (
    BM25Retriever,
    GraphRetriever,
    HybridKnowledgeRetriever,
    VectorRetriever,
)
from multi_agentic_rag.retrieval.reranker import (
    NoOpRerankingService,
    SentenceTransformerRerankingService,
    select_reranker,
)


class FakeBM25Repository:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def search_chunks(self, query_text: str, **kwargs) -> list[RetrievalResult]:
        self.calls.append(kwargs)
        return [
            _result("a", 0.9, ["bm25"]),
            _result("b", 0.5, ["bm25"]),
        ]


class FakeVectorRepository:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def query(self, query_text: str, **kwargs) -> list[RetrievalResult]:
        self.calls.append(kwargs)
        return [_result("v", 0.9, ["vector"])]


class FakeGraphRepository:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def related_chunk_ids(self, **kwargs) -> list[str]:
        self.calls.append(kwargs)
        return ["g"]


class FakeGraphChunkRepository:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def list_chunks_by_ids(self, chunk_ids: list[str], **kwargs) -> list[RetrievalResult]:
        self.calls.append({"chunk_ids": chunk_ids, **kwargs})
        return [_result("g", 1.0, ["graph"])]


class FakeRetriever:
    def __init__(self, results: list[RetrievalResult]) -> None:
        self.results = results

    async def retrieve(self, query_text: str, **kwargs) -> list[RetrievalResult]:
        return self.results


def _result(chunk_id: str, score: float, sources: list[str]) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        document_id="doc",
        document_version_id="dv",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        source_name="source.md",
        page=1,
        text=f"text {chunk_id}",
        score=score,
        sources=sources,
    )


def test_bm25_retriever_uses_repository() -> None:
    repository = FakeBM25Repository()
    results = asyncio.run(
        BM25Retriever(repository).retrieve(
            "query",
            system_name="PROJECT_1",
            kb_name="default",
        )
    )

    assert [result.chunk_id for result in results] == ["a", "b"]
    assert repository.calls[0]["active_only"] is True


def test_retrievers_allow_historical_lookup_when_version_is_explicit() -> None:
    bm25_repository = FakeBM25Repository()
    vector_repository = FakeVectorRepository()
    graph_repository = FakeGraphRepository()
    chunk_repository = FakeGraphChunkRepository()

    asyncio.run(
        BM25Retriever(bm25_repository).retrieve(
            "query",
            system_name="PROJECT_1",
            version="v1",
        )
    )
    asyncio.run(
        VectorRetriever(vector_repository).retrieve(
            "query",
            system_name="PROJECT_1",
            version="v1",
        )
    )
    asyncio.run(
        GraphRetriever(graph_repository, chunk_repository).retrieve(
            "query",
            system_name="PROJECT_1",
            version="v1",
        )
    )

    assert bm25_repository.calls[0]["active_only"] is False
    assert vector_repository.calls[0]["active_only"] is False
    assert graph_repository.calls[0]["active_only"] is False
    assert chunk_repository.calls[0]["active_only"] is False


def test_hybrid_retriever_fuses_and_deduplicates() -> None:
    hybrid = HybridKnowledgeRetriever(
        bm25=FakeRetriever([_result("a", 0.9, ["bm25"]), _result("b", 0.8, ["bm25"])]),
        vector=FakeRetriever([_result("b", 0.7, ["vector"]), _result("c", 0.6, ["vector"])]),
        graph=FakeRetriever([_result("a", 1.0, ["graph"])]),
        reranker=NoOpRerankingService(),
    )

    results = asyncio.run(hybrid.retrieve("query", system_name="PROJECT_1", top_k=3))

    assert [result.chunk_id for result in results] == ["a", "b", "c"]
    assert results[0].sources == ["bm25", "graph"]
    assert results[1].sources == ["bm25", "vector"]


def test_reranker_receives_hf_token_from_settings() -> None:
    reranker = select_reranker(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            reranker_provider="sentence_transformers",
            reranker_model="fake-reranker",
            hf_token="hf_test",
        )
    )

    assert isinstance(reranker, SentenceTransformerRerankingService)
    assert reranker.hf_token == "hf_test"


def test_cross_encoder_load_passes_hf_token(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    class FakeModule:
        @staticmethod
        def CrossEncoder(model_name: str, *, token: str | None) -> FakeCrossEncoder:
            captured["model"] = model_name
            captured["token"] = token
            return FakeCrossEncoder()

    monkeypatch.setattr(reranker_module, "import_module", lambda name: FakeModule)
    reranker = SentenceTransformerRerankingService("fake-reranker", hf_token="hf_test")

    results = reranker.rerank("query", [_result("a", 0.1, ["bm25"])])

    assert captured == {"model": "fake-reranker", "token": "hf_test"}
    assert results[0].score == 0.75


class FakeCrossEncoder:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [0.75 for _ in pairs]
