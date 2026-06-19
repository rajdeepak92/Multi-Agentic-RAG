"""Typed domain records for the GraphRAG knowledge base."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from multi_agentic_rag.utils.hashing import stable_id


class DocumentStatus(StrEnum):
    """Lifecycle status for versioned evidence."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"


class IngestionRunStatus(StrEnum):
    """Lifecycle status for ingestion runs."""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DocumentInput(BaseModel):
    """Source input accepted by `KnowledgeBaseStoringAgent`.

    Attributes:
        path: Source file path to ingest.
        kb_name: Knowledge-base name or context, defaulting to `default`.
        metadata: Caller-provided metadata reserved for future orchestration layers.
    """

    path: Path
    kb_name: str = "default"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageText(BaseModel):
    """Text extracted from one source page or logical document unit.

    Attributes:
        page: One-based page number or logical page number.
        text: Extracted text that will be chunked.
        tables: Optional table renderings appended by PDF/DOCX parsers.
        extraction_method: Parser method that produced the text.
    """

    page: int
    text: str
    tables: list[str] = Field(default_factory=list)
    extraction_method: str


class SystemRecord(BaseModel):
    """Knowledge base system row.

    Attributes:
        system_id: Stable deterministic ID for the system.
        system_name: Human-readable system namespace used by CLI commands.
        created_at: UTC creation timestamp.
        metadata: Extensible JSON metadata stored in PostgreSQL.
    """

    system_id: str
    system_name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRecord(BaseModel):
    """Stable source document lineage.

    Attributes:
        document_id: Stable ID for a source document lineage.
        system_name: Owning system namespace.
        kb_name: Knowledge-base context.
        source_name: Original source filename.
        document_type: Inferred type such as `brd`, `srs`, `pdf`, or `docx`.
        created_at: UTC creation timestamp.
        metadata: Extensible JSON metadata stored with the document.
    """

    document_id: str
    system_name: str
    kb_name: str
    source_name: str
    document_type: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentVersionRecord(BaseModel):
    """Versioned source document metadata.

    Attributes:
        document_version_id: Stable ID for this specific source content/version.
        document_id: Stable parent document lineage ID.
        system_name: Owning system namespace.
        kb_name: Knowledge-base context.
        version: Caller-provided version label.
        status: Active or superseded lifecycle status.
        source_path: Managed source path copied into runtime storage.
        source_name: Original source filename.
        content_hash: SHA-256 digest of the original source file.
        created_at: UTC creation timestamp.
        supersedes_version_id: Older active version replaced by this version.
        superseded_by_version_id: Newer version that replaced this version.
        optimistic_lock_version: Integer used for future concurrent-update checks.
        metadata: Extensible JSON metadata stored with the version.
    """

    document_version_id: str
    document_id: str
    system_name: str
    kb_name: str
    version: str
    status: DocumentStatus
    source_path: str
    source_name: str
    content_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    supersedes_version_id: str | None = None
    superseded_by_version_id: str | None = None
    optimistic_lock_version: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_chunk_id(
    *,
    system_name: str,
    version: str,
    source_name: str,
    page: int,
    chunk_index: int,
    content_hash: str,
) -> str:
    """Create a deterministic chunk ID from lineage metadata and content hash.

    Args:
        system_name: Owning system namespace.
        version: Document version label.
        source_name: Original source filename.
        page: One-based page or logical page number.
        chunk_index: Zero-based chunk index across the document.
        content_hash: SHA-256 digest of the chunk text.

    Returns:
        Stable chunk ID suitable for PostgreSQL, Chroma, and Neo4j.
    """

    return stable_id(
        "chunk",
        system_name,
        version,
        source_name,
        page,
        chunk_index,
        content_hash,
    )


class ChunkRecord(BaseModel):
    """A retrievable text chunk.

    Attributes:
        chunk_id: Stable chunk ID.
        document_version_id: Version ID that produced this chunk.
        document_id: Parent document lineage ID.
        system_name: Owning system namespace.
        kb_name: Knowledge-base context.
        version: Document version label.
        status: Active or superseded lifecycle status.
        source_name: Original source filename.
        page: One-based page or logical page number.
        section_title: Best-effort heading inferred from page text.
        chunk_index: Zero-based chunk index across the document.
        content_hash: SHA-256 digest of chunk text.
        text: Chunk body text.
        metadata: Extensible JSON metadata, including parser details.
    """

    chunk_id: str
    document_version_id: str
    document_id: str
    system_name: str
    kb_name: str
    version: str
    status: DocumentStatus
    source_name: str
    page: int
    section_title: str | None = None
    chunk_index: int
    content_hash: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FactRecord(BaseModel):
    """Extracted fact with evidence lineage.

    Attributes:
        fact_id: Stable fact ID.
        fact_key: Semantic key, such as `threshold:temperature`.
        fact_type: Extractor category, such as `requirement` or `protocol`.
        value: Extracted value.
        document_version_id: Version ID that produced this fact.
        document_id: Parent document lineage ID.
        chunk_id: Source chunk ID.
        system_name: Owning system namespace.
        kb_name: Knowledge-base context.
        version: Document version label.
        status: Active or superseded lifecycle status.
        evidence: Source-grounded evidence text.
        unit: Optional unit for numeric values.
        requirement_id: Requirement identifier linked to the fact when known.
        semantic_key: Stable comparison key used by delta analysis.
        metadata: Extensible JSON metadata from the extractor.
    """

    fact_id: str
    fact_key: str
    fact_type: str
    value: str
    document_version_id: str
    document_id: str
    chunk_id: str
    system_name: str
    kb_name: str
    version: str
    status: DocumentStatus
    evidence: str
    unit: str | None = None
    requirement_id: str | None = None
    semantic_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequirementRecord(BaseModel):
    """Requirement projection row.

    Attributes:
        requirement_id: Requirement identifier extracted from source text.
        document_version_id: Version ID where the requirement was found.
        document_id: Parent document lineage ID.
        chunk_id: Source chunk ID.
        system_name: Owning system namespace.
        kb_name: Knowledge-base context.
        version: Document version label.
        status: Active or superseded lifecycle status.
        text: Evidence text for the requirement.
        metadata: Extensible JSON metadata.
    """

    requirement_id: str
    document_version_id: str
    document_id: str
    chunk_id: str
    system_name: str
    kb_name: str
    version: str
    status: DocumentStatus
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityRecord(BaseModel):
    """Entity projection row.

    Attributes:
        entity_id: Stable entity ID.
        entity_type: Entity category, such as `sensor`, `protocol`, or `device`.
        name: Human-readable entity name.
        document_version_id: Version ID where the entity was mentioned.
        document_id: Parent document lineage ID.
        chunk_id: Source chunk ID.
        system_name: Owning system namespace.
        kb_name: Knowledge-base context.
        version: Document version label.
        status: Active or superseded lifecycle status.
        metadata: Extensible JSON metadata.
    """

    entity_id: str
    entity_type: str
    name: str
    document_version_id: str
    document_id: str
    chunk_id: str
    system_name: str
    kb_name: str
    version: str
    status: DocumentStatus
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeltaRecord(BaseModel):
    """Deterministic change record between document versions.

    Attributes:
        delta_id: Stable delta ID.
        system_name: Owning system namespace.
        kb_name: Knowledge-base context.
        from_document_version_id: Previous version ID.
        to_document_version_id: New version ID.
        from_version: Previous version label.
        to_version: New version label.
        fact_key: Fact semantic key compared across versions.
        change_type: Added, removed, modified, or unchanged.
        change_magnitude: Deterministic magnitude label.
        old_value: Previous value, if any.
        new_value: New value, if any.
        affected_requirement_id: Requirement linked to the changed fact.
        risk_level: Deterministic risk label.
        evidence: Source evidence snippets for the comparison.
    """

    delta_id: str
    system_name: str
    kb_name: str
    from_document_version_id: str
    to_document_version_id: str
    from_version: str
    to_version: str
    fact_key: str | None = None
    change_type: Literal["added", "removed", "modified", "unchanged"]
    change_magnitude: str
    old_value: str | None = None
    new_value: str | None = None
    affected_requirement_id: str | None = None
    risk_level: str
    evidence: list[str] = Field(default_factory=list)


class IngestionRunRecord(BaseModel):
    """Ingestion run state.

    Attributes:
        ingestion_run_id: Stable run ID.
        system_name: Owning system namespace.
        kb_name: Knowledge-base context.
        document_id: Persisted document ID once known.
        document_version_id: Persisted version ID once known.
        version: Caller-provided version label.
        status: Started, succeeded, or failed run state.
        started_at: UTC run start timestamp.
        ended_at: UTC run end timestamp.
        error_message: Failure detail when status is failed.
        metadata: Extensible JSON metadata for source path and hash.
    """

    ingestion_run_id: str
    system_name: str
    kb_name: str
    document_id: str | None = None
    document_version_id: str | None = None
    version: str
    status: IngestionRunStatus
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResult(BaseModel):
    """CLI-facing ingestion result.

    Attributes:
        document_id: Stable document lineage ID.
        document_version_id: Stable version ID.
        chunks_count: Number of chunks produced.
        facts_count: Number of facts extracted.
        deltas_count: Number of deltas produced.
        postgres_status: Persistence status string.
        chroma_status: Vector indexing status string.
        neo4j_status: Graph projection status string.
        bm25_status: PostgreSQL FTS readiness status string.
        ingestion_run_id: Stable ingestion run ID.
        warnings: Non-fatal runtime warnings.
    """

    document_id: str
    document_version_id: str
    chunks_count: int
    facts_count: int
    deltas_count: int
    postgres_status: str
    chroma_status: str
    neo4j_status: str
    bm25_status: str
    ingestion_run_id: str
    warnings: list[str] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    """Ranked retrieval result.

    Attributes:
        chunk_id: Retrieved chunk ID.
        document_id: Parent document lineage ID.
        document_version_id: Version ID for the chunk.
        system_name: Owning system namespace.
        kb_name: Knowledge-base context.
        version: Document version label.
        source_name: Original source filename.
        page: One-based page or logical page number.
        text: Retrieved chunk text.
        score: Retrieval or fused score.
        sources: Retrieval signals that contributed to the result.
        metadata: Extensible metadata from the backing store.
    """

    chunk_id: str
    document_id: str
    document_version_id: str
    system_name: str
    kb_name: str
    version: str
    source_name: str
    page: int
    text: str
    score: float
    sources: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
