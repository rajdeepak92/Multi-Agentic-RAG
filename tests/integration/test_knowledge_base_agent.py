from __future__ import annotations

import asyncio

import pytest

from multi_agentic_rag.agents import KnowledgeBaseStoringAgent
from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import (
    ChunkRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    DocumentVersionRecord,
    FactRecord,
    IngestionRunRecord,
    SystemRecord,
)
from multi_agentic_rag.exceptions import IngestionError


class FakePostgresAgent:
    def __init__(self) -> None:
        self.active: DocumentVersionRecord | None = None
        self.chunks_by_version: dict[str, list[ChunkRecord]] = {}
        self.facts_by_version: dict[str, list[FactRecord]] = {}
        self.runs: list[IngestionRunRecord] = []
        self.persisted: list[tuple[DocumentVersionRecord, list[DeltaRecord]]] = []
        self.failed: list[str] = []

    async def begin_run(self, run: IngestionRunRecord) -> None:
        self.runs.append(run)

    async def fail_run(self, ingestion_run_id: str, error_message: str) -> None:
        self.failed.append(error_message)

    async def succeed_run(
        self,
        ingestion_run_id: str,
        *,
        document_id: str,
        document_version_id: str,
    ) -> None:
        return None

    async def active_version(
        self, *, system_name: str, kb_name: str
    ) -> DocumentVersionRecord | None:
        return self.active

    async def facts_for_version(self, document_version_id: str) -> list[FactRecord]:
        return self.facts_by_version.get(document_version_id, [])

    async def chunks_for_version(self, document_version_id: str) -> list[ChunkRecord]:
        return self.chunks_by_version.get(document_version_id, [])

    async def persist(
        self,
        *,
        system: SystemRecord,
        document: DocumentRecord,
        document_version: DocumentVersionRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
        superseded_version_id: str | None,
    ) -> None:
        if superseded_version_id and self.active:
            self.active = self.active.model_copy(
                update={
                    "status": DocumentStatus.SUPERSEDED,
                    "superseded_by_version_id": document_version.document_version_id,
                }
            )
        if document_version.status == DocumentStatus.ACTIVE:
            self.active = document_version
        self.chunks_by_version[document_version.document_version_id] = chunks
        self.facts_by_version[document_version.document_version_id] = facts
        self.persisted.append((document_version, deltas))

    async def check_bm25(self) -> tuple[bool, str]:
        return True, "ready"


class FakeChromaAgent:
    def __init__(self, *, indexed_count: int | None = None) -> None:
        self.indexed = 0
        self.indexed_count = indexed_count
        self.batches: list[list[ChunkRecord]] = []

    def index(self, chunks: list[ChunkRecord]) -> int:
        count = len(chunks) if self.indexed_count is None else self.indexed_count
        self.indexed += count
        self.batches.append(chunks)
        return count

    def check(self) -> tuple[bool, str]:
        return True, "ready"


class FakeNeo4jAgent:
    def __init__(self) -> None:
        self.projected = 0

    def check(self) -> tuple[bool, str]:
        return True, "ready"

    def project(self, **kwargs) -> None:
        self.projected += 1


@pytest.mark.integration
def test_txt_markdown_ingest_and_v1_v2_delta(tmp_path) -> None:
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://user:pass@localhost/db",
        multi_agentic_rag_home=tmp_path / ".marag",
        document_store_path=tmp_path / ".marag" / "documents",
        object_store_path=tmp_path / ".marag" / "objects",
        manifest_store_path=tmp_path / ".marag" / "manifests",
        chroma_path=tmp_path / ".marag" / "chroma",
        chunk_size=500,
        chunk_overlap=0,
        graphrag_required=True,
    )
    postgres = FakePostgresAgent()
    chroma = FakeChromaAgent()
    neo4j = FakeNeo4jAgent()
    agent = KnowledgeBaseStoringAgent(
        settings=settings,
        postgres_agent=postgres,
        chroma_agent=chroma,
        neo4j_agent=neo4j,
    )
    v1 = tmp_path / "system_brd_v1.md"
    v2 = tmp_path / "system_brd_v2.txt"
    v1.write_text(
        "BRD\nREQ-1 temperature threshold maximum is 80 C. MQTT enabled.", encoding="utf-8"
    )
    v2.write_text(
        "BRD\nREQ-1 temperature threshold maximum is 90 C. REST enabled.", encoding="utf-8"
    )

    first = asyncio.run(agent.ingest(v1, "default", system="PROJECT_1", version="v1"))
    second = asyncio.run(agent.ingest(v2, "default", system="PROJECT_1", version="v2"))

    assert first.chunks_count == 1
    assert second.deltas_count > 0
    assert postgres.active is not None
    assert postgres.active.version == "v2"
    assert any(
        delta.change_type == "modified" for _, deltas in postgres.persisted for delta in deltas
    )
    assert chroma.indexed == 3
    assert second.chroma_status == "indexed:1;superseded_refreshed:1"
    assert chroma.batches[-1][0].status == DocumentStatus.SUPERSEDED
    assert neo4j.projected == 2


@pytest.mark.integration
def test_same_version_reingest_stays_active_after_partial_failure(tmp_path) -> None:
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://user:pass@localhost/db",
        multi_agentic_rag_home=tmp_path / ".marag",
        document_store_path=tmp_path / ".marag" / "documents",
        object_store_path=tmp_path / ".marag" / "objects",
        manifest_store_path=tmp_path / ".marag" / "manifests",
        chroma_path=tmp_path / ".marag" / "chroma",
        chunk_size=500,
        chunk_overlap=0,
        graphrag_required=True,
    )
    source = tmp_path / "system_brd_v1.md"
    source.write_text("BRD\nREQ-1 temperature threshold maximum is 80 C.", encoding="utf-8")
    postgres = FakePostgresAgent()
    first_attempt = KnowledgeBaseStoringAgent(
        settings=settings,
        postgres_agent=postgres,
        chroma_agent=FakeChromaAgent(indexed_count=0),
        neo4j_agent=FakeNeo4jAgent(),
    )

    with pytest.raises(IngestionError, match="Chroma indexed 0 chunks"):
        asyncio.run(first_attempt.ingest(source, "default", system="PROJECT_1", version="v1"))

    retry_chroma = FakeChromaAgent()
    retry = KnowledgeBaseStoringAgent(
        settings=settings,
        postgres_agent=postgres,
        chroma_agent=retry_chroma,
        neo4j_agent=FakeNeo4jAgent(),
    )
    result = asyncio.run(retry.ingest(source, "default", system="PROJECT_1", version="v1"))

    assert result.chroma_status == "indexed:1"
    assert postgres.active is not None
    assert postgres.active.status == DocumentStatus.ACTIVE
    assert postgres.persisted[-1][0].status == DocumentStatus.ACTIVE
    indexed_batches = [batch for batch in retry_chroma.batches if batch]
    assert indexed_batches[-1][0].status == DocumentStatus.ACTIVE


@pytest.mark.integration
def test_ingest_fails_when_no_facts_are_extracted(tmp_path) -> None:
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://user:pass@localhost/db",
        multi_agentic_rag_home=tmp_path / ".marag",
        document_store_path=tmp_path / ".marag" / "documents",
        object_store_path=tmp_path / ".marag" / "objects",
        manifest_store_path=tmp_path / ".marag" / "manifests",
        chroma_path=tmp_path / ".marag" / "chroma",
        chunk_size=500,
        chunk_overlap=0,
        graphrag_required=True,
    )
    postgres = FakePostgresAgent()
    agent = KnowledgeBaseStoringAgent(
        settings=settings,
        postgres_agent=postgres,
        chroma_agent=FakeChromaAgent(),
        neo4j_agent=FakeNeo4jAgent(),
    )
    source = tmp_path / "notes_v1.md"
    source.write_text(
        "This document has prose but no extractable requirement facts.",
        encoding="utf-8",
    )

    with pytest.raises(IngestionError, match="No facts were extracted"):
        asyncio.run(agent.ingest(source, "default", system="PROJECT_1", version="v1"))

    assert postgres.failed


@pytest.mark.integration
def test_ingest_fails_when_chroma_does_not_index_every_chunk(tmp_path) -> None:
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://user:pass@localhost/db",
        multi_agentic_rag_home=tmp_path / ".marag",
        document_store_path=tmp_path / ".marag" / "documents",
        object_store_path=tmp_path / ".marag" / "objects",
        manifest_store_path=tmp_path / ".marag" / "manifests",
        chroma_path=tmp_path / ".marag" / "chroma",
        chunk_size=500,
        chunk_overlap=0,
        graphrag_required=True,
    )
    postgres = FakePostgresAgent()
    agent = KnowledgeBaseStoringAgent(
        settings=settings,
        postgres_agent=postgres,
        chroma_agent=FakeChromaAgent(indexed_count=0),
        neo4j_agent=FakeNeo4jAgent(),
    )
    source = tmp_path / "system_brd_v1.md"
    source.write_text("BRD\nREQ-1 temperature threshold maximum is 80 C.", encoding="utf-8")

    with pytest.raises(IngestionError, match="Chroma indexed 0 chunks"):
        asyncio.run(agent.ingest(source, "default", system="PROJECT_1", version="v1"))

    assert postgres.failed
