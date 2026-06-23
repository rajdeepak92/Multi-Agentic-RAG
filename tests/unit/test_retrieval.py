from __future__ import annotations

import asyncio
import os

import multi_agentic_rag.retrieval.reranker as reranker_module
from multi_agentic_rag.agents.chat import (
    EVIDENCE_NOT_FOUND_MESSAGE,
    DocumentScopedChatAgent,
)
from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import GraphMatch, RetrievalResult
from multi_agentic_rag.retrieval import (
    BM25Retriever,
    EvidenceValidator,
    GraphRetriever,
    HybridKnowledgeRetriever,
    VectorRetriever,
)
from multi_agentic_rag.retrieval.reranker import (
    NoOpRerankingService,
    SentenceTransformerRerankingService,
    select_reranker,
)

PROJECT_CACHE_ENV_VARS = (
    "PROJECT_ROOT",
    "GLOBAL_CACHE_DIR",
    "MODEL_CACHE_DIR",
    "DATABASE_CACHE_DIR",
    "VECTORSTORE_CACHE_DIR",
    "GRAPH_CACHE_DIR",
    "HF_HOME",
    "TRANSFORMERS_CACHE",
    "SENTENCE_TRANSFORMERS_HOME",
    "TORCH_HOME",
    "HF_REASON_CACHE_DIR",
    "CHROMA_PATH",
    "MULTI_AGENTIC_RAG_HOME",
    "DOCUMENT_STORE_PATH",
    "OBJECT_STORE_PATH",
    "MANIFEST_STORE_PATH",
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


class FakeGraphMatchRepository:
    def __init__(self, matches: list[GraphMatch]) -> None:
        self.matches = matches
        self.calls: list[dict] = []

    def related_chunk_matches(self, **kwargs) -> list[GraphMatch]:
        self.calls.append(kwargs)
        return self.matches

    def related_chunk_ids(self, **kwargs) -> list[str]:
        self.calls.append(kwargs)
        return [match.chunk_id for match in self.matches]


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


def test_graph_retriever_hydrates_scored_matches_with_metadata() -> None:
    graph_repository = FakeGraphMatchRepository(
        [
            GraphMatch(
                chunk_id="g",
                score=2.0,
                reason="fact match: threshold",
                path=["Fact:threshold", "Chunk:g"],
                matched_terms=["threshold"],
            ),
            GraphMatch(
                chunk_id="g",
                score=1.5,
                reason="entity match: temperature",
                path=["Entity:temperature", "Chunk:g"],
                matched_terms=["temperature"],
            ),
        ]
    )
    chunk_repository = FakeGraphChunkRepository()

    results = asyncio.run(
        GraphRetriever(graph_repository, chunk_repository).retrieve(
            "temperature threshold",
            system_name="PROJECT_1",
            top_k=5,
        )
    )

    assert results[0].chunk_id == "g"
    assert results[0].score == 3.5
    assert results[0].sources == ["graph"]
    assert results[0].metadata["graph_path_count"] == 2
    assert results[0].metadata["graph_matched_terms"] == ["temperature", "threshold"]
    assert graph_repository.calls[0]["active_only"] is True


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
    assert results[0].metadata["evidence_path"][0] == "System:PROJECT_1"


def test_hybrid_retriever_preserves_graph_metadata_and_boosts_overlap() -> None:
    graph_result = _result("a", 4.0, ["graph"]).model_copy(
        update={
            "metadata": {
                "graph_score": 4.0,
                "graph_path_count": 2,
                "graph_matches": [
                    {
                        "reason": "requirement match: REQ-1",
                        "path": ["Requirement:REQ-1", "Chunk:a"],
                        "matched_terms": ["req-1"],
                    }
                ],
            }
        }
    )
    hybrid = HybridKnowledgeRetriever(
        bm25=FakeRetriever([_result("b", 0.9, ["fts"]), _result("a", 0.8, ["fts"])]),
        graph=FakeRetriever([graph_result]),
        reranker=NoOpRerankingService(),
    )

    results = asyncio.run(hybrid.retrieve("REQ-1", system_name="PROJECT_1", top_k=2))

    assert results[0].chunk_id == "a"
    assert results[0].sources == ["fts", "graph"]
    assert results[0].metadata["graph_matches"][0]["reason"] == "requirement match: REQ-1"


def test_hybrid_retriever_allows_relevant_graph_only_result_into_top_five() -> None:
    graph_result = _result("g", 6.0, ["graph"]).model_copy(
        update={"metadata": {"graph_score": 6.0, "graph_path_count": 3}}
    )
    hybrid = HybridKnowledgeRetriever(
        bm25=FakeRetriever([_result(f"b{index}", 1.0 - index / 10, ["fts"]) for index in range(5)]),
        graph=FakeRetriever([graph_result]),
        reranker=NoOpRerankingService(),
    )

    results = asyncio.run(
        hybrid.retrieve("temperature threshold", system_name="PROJECT_1", top_k=5)
    )

    assert "g" in [result.chunk_id for result in results]


def test_hybrid_retriever_runs_backends_concurrently() -> None:
    async def run() -> list[RetrievalResult]:
        all_started = asyncio.Event()
        state = {"started": 0}

        class CoordinatedRetriever:
            def __init__(self, chunk_id: str, source: str) -> None:
                self.chunk_id = chunk_id
                self.source = source

            async def retrieve(self, query_text: str, **kwargs) -> list[RetrievalResult]:
                state["started"] += 1
                if state["started"] == 3:
                    all_started.set()
                await asyncio.wait_for(all_started.wait(), timeout=1)
                return [_result(self.chunk_id, 1.0, [self.source])]

        hybrid = HybridKnowledgeRetriever(
            bm25=CoordinatedRetriever("b", "bm25"),
            vector=CoordinatedRetriever("v", "vector"),
            graph=CoordinatedRetriever("g", "graph"),
            reranker=NoOpRerankingService(),
        )
        return await hybrid.retrieve("query", system_name="PROJECT_1", top_k=3)

    results = asyncio.run(run())

    assert [result.chunk_id for result in results] == ["b", "g", "v"]


def test_evidence_validator_drops_untraceable_results() -> None:
    valid = _result("a", 1.0, ["bm25"])
    missing_source = valid.model_copy(update={"chunk_id": "bad", "source_name": ""})
    missing_text = valid.model_copy(update={"chunk_id": "empty", "text": ""})

    evidence = EvidenceValidator().validate([missing_source, missing_text, valid])

    assert [result.chunk_id for result in evidence] == ["a"]
    assert evidence[0].rank == 1
    assert evidence[0].evidence_path[-1] == "Source:source.md#page=1"


def test_document_scoped_chat_refuses_without_evidence() -> None:
    class EmptyRetriever:
        async def retrieve(self, query_text: str, **kwargs) -> list[RetrievalResult]:
            return []

    answer = asyncio.run(
        DocumentScopedChatAgent(EmptyRetriever()).answer(
            "query",
            system_name="PROJECT_1",
        )
    )

    assert answer.refused is True
    assert answer.answer == EVIDENCE_NOT_FOUND_MESSAGE


def test_document_scoped_chat_renders_traceable_evidence() -> None:
    class EvidenceRetriever:
        async def retrieve(self, query_text: str, **kwargs) -> list[RetrievalResult]:
            return [_result("a", 1.0, ["bm25"])]

    answer = asyncio.run(
        DocumentScopedChatAgent(EvidenceRetriever()).answer(
            "query",
            system_name="PROJECT_1",
        )
    )

    assert answer.refused is False
    assert "source.md page 1, v1" in answer.answer
    assert answer.evidence[0].chunk_id == "a"


def test_reranker_receives_hf_token_from_settings(monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)
    reranker = select_reranker(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            reranker_provider="sentence_transformers",
            reranker_model="fake-reranker",
            hf_token="hf_test",
            _env_file=None,
        )
    )

    assert isinstance(reranker, SentenceTransformerRerankingService)
    assert reranker.hf_token == "hf_test"


def test_reranker_receives_device_from_settings(monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

    class FakeTorch:
        cuda = FakeCuda()

    def fake_import_module(name: str) -> object:
        if name == "torch":
            return FakeTorch()
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("multi_agentic_rag.runtime.device.import_module", fake_import_module)
    reranker = select_reranker(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            reranker_provider="sentence_transformers",
            reranker_model="fake-reranker",
            reranker_device="cuda",
            _env_file=None,
        )
    )

    assert isinstance(reranker, SentenceTransformerRerankingService)
    assert reranker.device == "cuda"


def test_reranker_configures_project_model_cache(tmp_path, monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)
    reranker = select_reranker(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            project_root=tmp_path,
            reranker_provider="sentence_transformers",
            reranker_model="fake-reranker",
            _env_file=None,
        )
    )

    assert isinstance(reranker, SentenceTransformerRerankingService)
    assert os.environ["SENTENCE_TRANSFORMERS_HOME"] == str(
        tmp_path / ".global_cache" / "models" / "sentence_transformers"
    )


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


def test_cross_encoder_load_passes_explicit_device(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    class FakeModule:
        @staticmethod
        def CrossEncoder(
            model_name: str,
            *,
            token: str | None,
            device: str,
        ) -> FakeCrossEncoder:
            captured["model"] = model_name
            captured["token"] = token
            captured["device"] = device
            return FakeCrossEncoder()

    monkeypatch.setattr(reranker_module, "import_module", lambda name: FakeModule)
    reranker = SentenceTransformerRerankingService(
        "fake-reranker",
        hf_token="hf_test",
        device="cuda",
    )

    results = reranker.rerank("query", [_result("a", 0.1, ["bm25"])])

    assert captured == {"model": "fake-reranker", "token": "hf_test", "device": "cuda"}
    assert results[0].score == 0.75


class FakeCrossEncoder:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [0.75 for _ in pairs]


def _clear_project_cache_env(monkeypatch) -> None:
    for env_name in PROJECT_CACHE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
