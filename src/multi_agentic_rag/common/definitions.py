"""Stable project-wide typed values."""

from __future__ import annotations

from enum import StrEnum


class ReasoningProviderName(StrEnum):
    """Supported structured reasoning providers."""

    OPENAI = "openai"
    GEMINI = "gemini"
    HUGGINGFACE = "huggingface"


class LexicalBackendName(StrEnum):
    """Supported PostgreSQL lexical retrieval implementations."""

    PG_TEXTSEARCH = "pg_textsearch"
    POSTGRES_NATIVE_FTS = "postgres_native_fts"


class RetrievalSourceName(StrEnum):
    """Physical retrieval stores used for evidence collection."""

    POSTGRES = "postgres"
    CHROMA = "chroma"
    NEO4J = "neo4j"


class IngestionStage(StrEnum):
    """Coarse ingestion workflow stages."""

    STARTED = "started"
    VALIDATED = "validated"
    DEPENDENCIES_READY = "dependencies_ready"
    LINEAGE_RESOLVED = "lineage_resolved"
    DOCUMENT_PARSED = "document_parsed"
    DOCUMENT_CHUNKED = "document_chunked"
    KNOWLEDGE_EXTRACTED = "knowledge_extracted"
    KNOWLEDGE_VALIDATED = "knowledge_validated"
    DELTAS_COMPUTED = "deltas_computed"
    POSTGRES_COMMITTED = "postgres_committed"
    CHROMA_INDEXED = "chroma_indexed"
    NEO4J_PROJECTED = "neo4j_projected"
    COMPLETED = "completed"
    FAILED = "failed"
