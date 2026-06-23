from __future__ import annotations

import asyncio
import os

import numpy as np
import pytest
from sqlalchemy.dialects import postgresql

import multi_agentic_rag.infrastructure.embeddings.provider as embedding_provider_module
from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import ArtifactManifest, ChunkRecord, DocumentStatus, FactRecord
from multi_agentic_rag.exceptions import ConfigError
from multi_agentic_rag.infrastructure.chroma import ChromaVectorRepository
from multi_agentic_rag.infrastructure.embeddings import (
    HashEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    select_embedding_provider,
)
from multi_agentic_rag.infrastructure.neo4j import Neo4jGraphRepository
from multi_agentic_rag.infrastructure.postgres import PostgresKnowledgeRepository
from multi_agentic_rag.infrastructure.postgres.models import ChunkModel
from multi_agentic_rag.infrastructure.postgres.repository import _is_transient_postgres_error
from multi_agentic_rag.infrastructure.postgres.session import normalize_async_dsn
from multi_agentic_rag.ingestion import chunk_pages, create_document_records
from multi_agentic_rag.ingestion.parser import PageText

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


def test_hash_embedding_provider_is_deterministic() -> None:
    provider = HashEmbeddingProvider(dimensions=8)

    assert provider.embed_query("same") == provider.embed_query("same")
    assert len(provider.embed_query("same")) == 8


def test_default_embedding_provider_uses_bge_m3(monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    provider = select_embedding_provider(
        Settings(postgres_dsn="postgresql+asyncpg://x", _env_file=None)
    )

    assert isinstance(provider, SentenceTransformerEmbeddingProvider)
    assert provider.model == "BAAI/bge-m3"


def test_settings_accepts_legacy_postgres_bm25_alias() -> None:
    settings = Settings(postgres_dsn="postgresql+asyncpg://x", bm25_backend="postgres")

    assert settings.bm25_backend == "postgres_fts"


def test_normalize_async_dsn_converts_tiger_sslmode_for_asyncpg() -> None:
    dsn = "postgresql://user:pass@example.com:39332/tsdb?sslmode=require"

    normalized = normalize_async_dsn(dsn)

    assert normalized == "postgresql+asyncpg://user:pass@example.com:39332/tsdb?ssl=require"


def test_postgres_retry_classifier_rejects_non_retryable_failures() -> None:
    assert _is_transient_postgres_error(RuntimeError("connection reset by peer")) is True
    assert (
        _is_transient_postgres_error(
            RuntimeError("pg_textsearch extension is not available in this database")
        )
        is False
    )
    assert (
        _is_transient_postgres_error(RuntimeError("password authentication failed for user"))
        is False
    )


def test_project_cache_defaults_create_global_cache_tree(tmp_path, monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://x",
        project_root=tmp_path,
        _env_file=None,
    )

    paths = settings.ensure_project_cache_paths()

    assert paths["global_cache_dir"] == tmp_path / ".global_cache"
    assert settings.chroma_path == tmp_path / ".global_cache" / "vectorstore" / "chroma"
    assert settings.multi_agentic_rag_home == tmp_path / ".global_cache" / "runtime"
    for path in paths.values():
        assert path.exists()
    assert os.environ["HF_HOME"] == str(tmp_path / ".global_cache" / "models" / "huggingface")
    assert os.environ["TRANSFORMERS_CACHE"] == str(
        tmp_path / ".global_cache" / "models" / "transformers"
    )
    assert os.environ["SENTENCE_TRANSFORMERS_HOME"] == str(
        tmp_path / ".global_cache" / "models" / "sentence_transformers"
    )
    assert os.environ["TORCH_HOME"] == str(tmp_path / ".global_cache" / "models" / "torch")


def test_project_cache_blank_values_fall_back_to_defaults(tmp_path, monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://x",
        project_root=tmp_path,
        global_cache_dir="",
        chroma_path="",
        multi_agentic_rag_home="",
        hf_reason_cache_dir="",
        _env_file=None,
    )

    settings.ensure_project_cache_paths()

    assert settings.global_cache_dir == tmp_path / ".global_cache"
    assert settings.chroma_path == tmp_path / ".global_cache" / "vectorstore" / "chroma"
    assert settings.multi_agentic_rag_home == tmp_path / ".global_cache" / "runtime"
    assert settings.hf_reason_cache_dir == tmp_path / ".global_cache" / "models" / "hf_reasoning"


def test_project_cache_rejects_paths_outside_project_root(tmp_path, monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-cache"
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://x",
        project_root=tmp_path,
        chroma_path=outside,
        _env_file=None,
    )

    with pytest.raises(ConfigError, match="must stay inside PROJECT_ROOT"):
        settings.ensure_project_cache_paths()


def test_chroma_repository_uses_global_cache_default(tmp_path, monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://x",
        project_root=tmp_path,
        _env_file=None,
    )

    repository = ChromaVectorRepository.from_settings(settings)

    assert repository.path == tmp_path / ".global_cache" / "vectorstore" / "chroma"


def test_embedding_provider_receives_hf_token_from_settings(monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)
    provider = select_embedding_provider(
        Settings(postgres_dsn="postgresql+asyncpg://x", hf_token="hf_test", _env_file=None)
    )

    assert isinstance(provider, SentenceTransformerEmbeddingProvider)
    assert provider.hf_token == "hf_test"


def test_embedding_provider_receives_device_from_settings(monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)
    provider = select_embedding_provider(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            embedding_device="cuda",
            _env_file=None,
        )
    )

    assert isinstance(provider, SentenceTransformerEmbeddingProvider)
    assert provider.device == "cuda"


def test_embedding_provider_configures_project_model_cache(tmp_path, monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://x",
        project_root=tmp_path,
        _env_file=None,
    )

    provider = select_embedding_provider(settings)

    assert isinstance(provider, SentenceTransformerEmbeddingProvider)
    assert os.environ["SENTENCE_TRANSFORMERS_HOME"] == str(
        tmp_path / ".global_cache" / "models" / "sentence_transformers"
    )


def test_sentence_transformer_load_passes_hf_token(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    class FakeModule:
        @staticmethod
        def SentenceTransformer(model: str, *, token: str | None) -> _FakeSentenceTransformerModel:
            captured["model"] = model
            captured["token"] = token
            return _FakeSentenceTransformerModel()

    monkeypatch.setattr(embedding_provider_module, "import_module", lambda name: FakeModule)

    provider = SentenceTransformerEmbeddingProvider("fake-model", hf_token="hf_test")
    provider.embed_documents(["text"])

    assert captured == {"model": "fake-model", "token": "hf_test"}


def test_sentence_transformer_load_passes_explicit_device(monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    class FakeModule:
        @staticmethod
        def SentenceTransformer(
            model: str,
            *,
            token: str | None,
            device: str,
        ) -> _FakeSentenceTransformerModel:
            captured["model"] = model
            captured["token"] = token
            captured["device"] = device
            return _FakeSentenceTransformerModel()

    monkeypatch.setattr(embedding_provider_module, "import_module", lambda name: FakeModule)

    provider = SentenceTransformerEmbeddingProvider(
        "fake-model",
        hf_token="hf_test",
        device="cuda",
    )
    provider.embed_documents(["text"])

    assert captured == {"model": "fake-model", "token": "hf_test", "device": "cuda"}


def test_sentence_transformer_provider_returns_plain_python_floats() -> None:
    provider = SentenceTransformerEmbeddingProvider("fake-model")
    provider._model = _FakeSentenceTransformerModel()

    vector = provider.embed_documents(["text"])[0]

    assert vector == [0.25, -0.5]
    assert all(type(value) is float for value in vector)


def test_chroma_query_filters_active_chunks_by_default(tmp_path) -> None:
    collection = _FakeChromaCollection()
    repository = ChromaVectorRepository(
        path=tmp_path,
        collection_name="test",
        embedding_provider=HashEmbeddingProvider(dimensions=8),
    )
    repository._collection = collection

    repository.query("temperature", system_name="PROJECT_1", kb_name="default")
    repository.query("temperature", system_name="PROJECT_1", kb_name="default", version="v1")

    assert collection.calls[0]["where"] == {
        "$and": [{"system_name": "PROJECT_1"}, {"kb_name": "default"}, {"status": "active"}]
    }
    assert collection.calls[1]["where"] == {
        "$and": [{"system_name": "PROJECT_1"}, {"kb_name": "default"}, {"version": "v1"}]
    }


def test_neo4j_related_chunk_query_filters_active_chunks_by_default() -> None:
    repository = Neo4jGraphRepository(Settings(postgres_dsn="postgresql+asyncpg://x"))
    session = _CapturingNeo4jSession()
    repository.session = lambda: session

    repository.related_chunk_ids(
        query_text="temperature",
        system_name="PROJECT_1",
        kb_name="default",
        version=None,
        top_k=5,
    )
    active_cypher = session.cypher
    repository.related_chunk_ids(
        query_text="temperature",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        top_k=5,
    )

    assert "v.status = $active_status" in active_cypher
    assert "c.status = $active_status" in active_cypher
    assert "$query_text" not in active_cypher
    assert "v.version = $version" in session.cypher
    assert "c.version = $version" in session.cypher
    assert "v.status = $active_status" not in session.cypher


def test_neo4j_graph_query_normalizes_terms_and_requirement_ids() -> None:
    repository = Neo4jGraphRepository(Settings(postgres_dsn="postgresql+asyncpg://x"))
    session = _CapturingNeo4jSession(
        records=[
            {
                "chunk_id": "chunk-1",
                "score": 2.3,
                "reason": "requirement match: REQ-1",
                "path": ["Requirement:REQ-1", "Chunk:chunk-1"],
                "matched_terms": ["req-1"],
            }
        ]
    )
    repository.session = lambda: session

    matches = repository.related_chunk_matches(
        query_text="temp limit REQ-1",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        top_k=5,
    )

    assert matches[0].chunk_id == "chunk-1"
    assert {"temp", "temperature", "limit", "threshold", "range", "req-1"}.issubset(
        set(session.params["terms"])
    )
    assert session.params["requirement_ids"] == ["req-1"]
    assert "Entity" in session.cypher
    assert "Fact" in session.cypher
    assert "Requirement" in session.cypher
    assert "CONTAINS toLower($query_text)" not in session.cypher


def test_neo4j_cypher_uses_only_graphrag_labels(tmp_path) -> None:
    source = tmp_path / "brd_v1.md"
    source.write_text("REQ-1 controller PLC1 uses MQTT.", encoding="utf-8")
    document, version = create_document_records(
        source=source,
        managed_source=source,
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        content_hash="hash",
        document_type="brd",
        previous_version_id=None,
    )
    chunks = chunk_pages(
        [PageText(page=1, text="REQ-1 controller PLC1 uses MQTT.", extraction_method="text")],
        document_version=version,
        chunk_size=500,
        chunk_overlap=0,
    )
    fact = FactRecord(
        fact_id="fact1",
        fact_key="requirement:REQ-1",
        fact_type="requirement",
        value="REQ-1",
        document_version_id=version.document_version_id,
        document_id=document.document_id,
        chunk_id=chunks[0].chunk_id,
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        status=DocumentStatus.ACTIVE,
        evidence="REQ-1 controller PLC1 uses MQTT.",
        requirement_id="REQ-1",
    )

    statements = Neo4jGraphRepository(
        Settings(postgres_dsn="postgresql+asyncpg://x")
    ).build_ingestion_cypher(
        document=document,
        document_version=version,
        chunks=chunks,
        facts=[fact],
        deltas=[],
    )
    cypher = "\n".join(query for query, _ in statements)

    assert "Coverage" not in cypher
    assert "GeneratedTest" not in cypher
    assert "TestRun" not in cypher
    assert "DocumentVersion" in cypher


def test_neo4j_cypher_projects_ingestion_relationship_map(tmp_path) -> None:
    source = tmp_path / "brd_v2.md"
    source.write_text(
        "REQ-1 temperature threshold maximum is 90 C. "
        "controller PLC1 uses MQTT topic factory/temp and POST /telemetry.",
        encoding="utf-8",
    )
    document, version = create_document_records(
        source=source,
        managed_source=source,
        system_name="PROJECT_1",
        kb_name="default",
        version="v2",
        content_hash="hash",
        document_type="brd",
        previous_version_id="old-version",
    )
    chunks = chunk_pages(
        [
            PageText(
                page=1,
                text=(
                    "REQ-1 temperature threshold maximum is 90 C. "
                    "controller PLC1 uses MQTT topic factory/temp and POST /telemetry."
                ),
                extraction_method="text",
            )
        ],
        document_version=version,
        chunk_size=500,
        chunk_overlap=0,
    )
    chunk = chunks[0]
    facts = [
        _fact(chunk, "1", "requirement", "requirement:REQ-1", "REQ-1", "REQ-1"),
        _fact(
            chunk,
            "2",
            "threshold",
            "threshold:temperature",
            "90",
            "REQ-1",
            metadata={"sensor": "temperature"},
        ),
        _fact(chunk, "3", "protocol", "protocol:mqtt", "MQTT", "REQ-1"),
        _fact(
            chunk,
            "4",
            "protocol_detail",
            "protocol_detail:rest:post:/telemetry",
            "POST /telemetry",
            "REQ-1",
            metadata={"protocol": "REST", "method": "POST", "path": "/telemetry"},
        ),
        _fact(chunk, "5", "device", "device:plc1", "PLC1", "REQ-1"),
        _fact(chunk, "6", "topic", "topic:mqtt:factory/temp", "factory/temp", "REQ-1"),
    ]

    statements = Neo4jGraphRepository(
        Settings(postgres_dsn="postgresql+asyncpg://x")
    ).build_ingestion_cypher(
        document=document,
        document_version=version,
        chunks=chunks,
        facts=facts,
        deltas=[],
    )
    cypher = "\n".join(query for query, _ in statements)

    assert "DESCRIBES_REQUIREMENT" in cypher
    assert "TRACES_TO_REQUIREMENT" in cypher
    assert "Passage" in cypher
    assert "Sentence" in cypher
    assert "HAS_PASSAGE" in cypher
    assert "HAS_SENTENCE" in cypher
    assert "THRESHOLD_FOR" in cypher
    assert "IMPLEMENTS_PROTOCOL" in cypher
    assert "DETAILS_PROTOCOL" in cypher
    assert "USES_TOPIC" in cypher
    assert "MENTIONS" in cypher
    assert "Entity:Sensor" in cypher
    assert "Entity:Device" in cypher
    assert "Entity:Protocol" in cypher
    assert "Entity:Topic" in cypher
    assert "old.status = $superseded_status" in cypher
    assert "c.status = $superseded_status" in cypher
    assert "p.status = $superseded_status" in cypher
    assert "s.status = $superseded_status" in cypher
    assert "f.status = $superseded_status" in cypher


def test_neo4j_cypher_uses_validated_llm_canonical_name_for_entities(tmp_path) -> None:
    source = tmp_path / "brd_v3.md"
    source.write_text("temperature threshold maximum is 90 C.", encoding="utf-8")
    document, version = create_document_records(
        source=source,
        managed_source=source,
        system_name="PROJECT_1",
        kb_name="default",
        version="v3",
        content_hash="hash",
        document_type="brd",
        previous_version_id=None,
    )
    chunk = chunk_pages(
        [PageText(page=1, text="temperature threshold maximum is 90 C.", extraction_method="text")],
        document_version=version,
        chunk_size=500,
        chunk_overlap=0,
    )[0]
    fact = _fact(
        chunk,
        "1",
        "threshold",
        "threshold:temperature",
        "90",
        None,
        metadata={
            "sensor": "temperature",
            "llm_review_status": "validated",
            "llm_canonical_name": "temperature-sensor-alpha",
        },
    )

    statements = Neo4jGraphRepository(
        Settings(postgres_dsn="postgresql+asyncpg://x")
    ).build_ingestion_cypher(
        document=document,
        document_version=version,
        chunks=[chunk],
        facts=[fact],
        deltas=[],
    )

    entity_payloads = [
        params for query, params in statements if "MERGE (e:Entity:Sensor" in query
    ]
    assert entity_payloads
    assert entity_payloads[0]["name"] == "temperature-sensor-alpha"


def test_postgres_readiness_requires_pg_textsearch_extension_and_index() -> None:
    repository = PostgresKnowledgeRepository(
        _FakeAsyncSessionFactory(
            [
                _FakeScalarResult(1),
                _FakeScalarResult(True),
                _FakeScalarResult("idx"),
                _FakeRowsResult([]),
            ]
        )
    )

    ready, message = asyncio.run(repository.check_connection())

    assert ready is True
    assert "pg_textsearch BM25 index" in message


def test_postgres_readiness_fails_when_pg_textsearch_extension_is_missing() -> None:
    repository = PostgresKnowledgeRepository(
        _FakeAsyncSessionFactory([_FakeScalarResult(1), _FakeScalarResult(False)])
    )

    ready, message = asyncio.run(repository.check_connection())

    assert ready is False
    assert "pg_textsearch extension" in message

    readiness = asyncio.run(
        PostgresKnowledgeRepository(
            _FakeAsyncSessionFactory([_FakeScalarResult(1), _FakeScalarResult(False)])
        ).check_lexical_readiness()
    )
    assert readiness.connected is True
    assert readiness.pg_textsearch_extension is False
    assert readiness.bm25_index is None


def test_postgres_readiness_fails_when_pg_textsearch_index_is_missing() -> None:
    repository = PostgresKnowledgeRepository(
        _FakeAsyncSessionFactory(
            [_FakeScalarResult(1), _FakeScalarResult(True), _FakeScalarResult(None)]
        )
    )

    ready, message = asyncio.run(repository.check_connection())

    assert ready is False
    assert "idx_chunks_text_bm25" in message

    readiness = asyncio.run(
        PostgresKnowledgeRepository(
            _FakeAsyncSessionFactory(
                [_FakeScalarResult(1), _FakeScalarResult(True), _FakeScalarResult(None)]
            )
        ).check_lexical_readiness()
    )
    assert readiness.connected is True
    assert readiness.pg_textsearch_extension is True
    assert readiness.bm25_index is False


def test_postgres_readiness_uses_native_fts_fallback() -> None:
    repository = PostgresKnowledgeRepository(
        _FakeAsyncSessionFactory([_FakeScalarResult(1), _FakeScalarResult("idx")]),
        bm25_backend="postgres_fts",
    )

    ready, message = asyncio.run(repository.check_connection())

    assert ready is True
    assert "native FTS index" in message


def test_postgres_search_chunks_uses_pg_textsearch_bm25_by_default() -> None:
    chunk = ChunkModel(
        chunk_id="chunk-1",
        document_version_id="version-1",
        document_id="doc-1",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        status=DocumentStatus.ACTIVE.value,
        source_name="source.md",
        page=1,
        section_title=None,
        chunk_index=0,
        content_hash="hash",
        text="REQ-1 temperature threshold maximum is 90 C.",
        metadata_json={},
    )
    session_factory = _FakeAsyncSessionFactory([_FakeRowsResult([(chunk, -2.4)])])
    repository = PostgresKnowledgeRepository(session_factory)

    results = asyncio.run(
        repository.search_chunks(
            "temperature threshold",
            system_name="PROJECT_1",
            kb_name="default",
            top_k=5,
        )
    )

    sql = session_factory.statements[0]
    assert "<@>" in sql
    assert "to_bm25query" in sql
    assert "idx_chunks_text_bm25" in sql
    assert "score <" in sql or "< %(param_1)" in sql
    assert "ORDER BY score ASC" in sql
    assert session_factory.params[0] == {"query_text": "temperature threshold"}
    assert results[0].chunk_id == "chunk-1"
    assert results[0].score == -2.4
    assert results[0].sources == ["bm25"]


def test_postgres_search_chunks_uses_native_fts_fallback() -> None:
    chunk = ChunkModel(
        chunk_id="chunk-1",
        document_version_id="version-1",
        document_id="doc-1",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        status=DocumentStatus.ACTIVE.value,
        source_name="source.md",
        page=1,
        section_title=None,
        chunk_index=0,
        content_hash="hash",
        text="REQ-1 temperature threshold maximum is 90 C.",
        metadata_json={},
    )
    session_factory = _FakeAsyncSessionFactory([_FakeRowsResult([(chunk, 0.42)])])
    repository = PostgresKnowledgeRepository(session_factory, bm25_backend="postgres_fts")

    results = asyncio.run(
        repository.search_chunks(
            "temperature threshold",
            system_name="PROJECT_1",
            kb_name="default",
            top_k=5,
        )
    )

    sql = session_factory.statements[0]
    assert " @@ " in sql
    assert "websearch_to_tsquery" in sql
    assert "ts_rank_cd" in sql
    assert "to_bm25query" not in sql
    assert results[0].sources == ["fts"]


def test_postgres_current_search_includes_active_canonical_fact_chunks() -> None:
    repository = PostgresKnowledgeRepository(_FakeAsyncSessionFactory([_FakeRowsResult([])]))

    asyncio.run(
        repository.search_chunks(
            "temperature threshold",
            system_name="PROJECT_1",
            kb_name="default",
            top_k=5,
        )
    )

    sql = repository.session_factory.statements[0]
    assert "canonical_facts" in sql
    assert "active_fact_id" in sql
    assert "chunks.status = " in sql


def test_neo4j_cypher_projects_user_story_artifact_lineage() -> None:
    manifest = ArtifactManifest(
        artifact_id="artifact-1",
        story_id="US-001",
        generated_file_path="generated/PROJECT_1/default/v1/user_stories/US-001.yaml",
        debug_json_path="generated/PROJECT_1/default/v1/debug/US-001.json",
        source_chunk_ids=["chunk-1"],
        model="gpt-5.5",
        prompt_version="prompt-v1",
        validation_status="passed",
    )
    statements = Neo4jGraphRepository(
        Settings(postgres_dsn="postgresql+asyncpg://x")
    ).build_user_story_artifact_cypher(
        manifest=manifest,
        story_payload={
            "id": "US-001",
            "title": "Monitor threshold",
            "status": "draft",
            "priority": "high",
            "persona": "operator",
            "user_story": "As an operator, I want threshold monitoring.",
        },
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
    )
    cypher = "\n".join(query for query, _ in statements)

    assert "UserStory" in cypher
    assert "Artifact" in cypher
    assert "DERIVED_FROM_VERSION" in cypher
    assert "TRACES_TO_CHUNK" in cypher


def _fact(
    chunk: ChunkRecord,
    suffix: str,
    fact_type: str,
    fact_key: str,
    value: str,
    requirement_id: str | None,
    *,
    metadata: dict | None = None,
) -> FactRecord:
    return FactRecord(
        fact_id=f"fact-{suffix}",
        fact_key=fact_key,
        fact_type=fact_type,
        value=value,
        document_version_id=chunk.document_version_id,
        document_id=chunk.document_id,
        chunk_id=chunk.chunk_id,
        system_name=chunk.system_name,
        kb_name=chunk.kb_name,
        version=chunk.version,
        status=DocumentStatus.ACTIVE,
        evidence=chunk.text,
        requirement_id=requirement_id,
        metadata=metadata or {},
    )


class _FakeChromaCollection:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def query(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


class _CapturingNeo4jSession:
    def __init__(self, records: list[dict] | None = None) -> None:
        self.cypher = ""
        self.params: dict = {}
        self.records = records or []

    def __enter__(self) -> _CapturingNeo4jSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def run(self, cypher: str, params: dict) -> list:
        self.cypher = cypher
        self.params = params
        return self.records


class _FakeSentenceTransformerModel:
    def encode(self, texts: list[str], *, normalize_embeddings: bool) -> list:
        return [np.array([np.float32(0.25), np.float32(-0.5)]) for _ in texts]


class _FakeAsyncSessionFactory:
    def __init__(self, results: list[object]) -> None:
        self.results = results
        self.statements: list[str] = []
        self.params: list[dict[str, object] | None] = []

    def __call__(self) -> _FakeAsyncSessionFactory:
        return self

    async def __aenter__(self) -> _FakeAsyncSessionFactory:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: object, params: dict[str, object] | None = None) -> object:
        self.statements.append(_compile_sql(statement))
        self.params.append(params)
        return self.results.pop(0)


class _FakeScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _FakeRowsResult:
    def __init__(self, rows: list[tuple[ChunkModel, float]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[ChunkModel, float]]:
        return self.rows


def _compile_sql(statement: object) -> str:
    if hasattr(statement, "compile"):
        return str(statement.compile(dialect=postgresql.dialect()))
    return str(statement)


def _clear_project_cache_env(monkeypatch) -> None:
    for env_name in PROJECT_CACHE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
