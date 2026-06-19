from __future__ import annotations

import numpy as np

import multi_agentic_rag.infrastructure.embeddings.provider as embedding_provider_module
from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import ChunkRecord, DocumentStatus, FactRecord
from multi_agentic_rag.infrastructure.chroma import ChromaVectorRepository
from multi_agentic_rag.infrastructure.embeddings import (
    HashEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    select_embedding_provider,
)
from multi_agentic_rag.infrastructure.neo4j import Neo4jGraphRepository
from multi_agentic_rag.ingestion import chunk_pages, create_document_records
from multi_agentic_rag.ingestion.parser import PageText


def test_hash_embedding_provider_is_deterministic() -> None:
    provider = HashEmbeddingProvider(dimensions=8)

    assert provider.embed_query("same") == provider.embed_query("same")
    assert len(provider.embed_query("same")) == 8


def test_default_embedding_provider_uses_bge_m3() -> None:
    provider = select_embedding_provider(Settings(postgres_dsn="postgresql+asyncpg://x"))

    assert isinstance(provider, SentenceTransformerEmbeddingProvider)
    assert provider.model == "BAAI/bge-m3"


def test_embedding_provider_receives_hf_token_from_settings() -> None:
    provider = select_embedding_provider(
        Settings(postgres_dsn="postgresql+asyncpg://x", hf_token="hf_test")
    )

    assert isinstance(provider, SentenceTransformerEmbeddingProvider)
    assert provider.hf_token == "hf_test"


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

    assert "f.status = $active_status" in active_cypher
    assert "c.status = $active_status" in active_cypher
    assert "f.version = $version AND c.version = $version" in session.cypher
    assert "f.status = $active_status" not in session.cypher


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
    assert "f.status = $superseded_status" in cypher


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
    def __init__(self) -> None:
        self.cypher = ""

    def __enter__(self) -> _CapturingNeo4jSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def run(self, cypher: str, params: dict) -> list:
        self.cypher = cypher
        return []


class _FakeSentenceTransformerModel:
    def encode(self, texts: list[str], *, normalize_embeddings: bool) -> list:
        return [np.array([np.float32(0.25), np.float32(-0.5)]) for _ in texts]
