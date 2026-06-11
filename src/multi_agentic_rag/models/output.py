"""Structured output contracts for API/CLI responses."""

from __future__ import annotations

from pydantic import BaseModel, Field

from multi_agentic_rag.models.chunk import ChunkRecord
from multi_agentic_rag.models.delta import DeltaRecord
from multi_agentic_rag.models.document import DocumentRecord
from multi_agentic_rag.models.graph import FactRecord


class EvidenceRecord(BaseModel):
    """Citation/evidence payload used in answers."""

    document_id: str
    chunk_id: str
    system_name: str
    version: str
    source_name: str
    page: int
    text: str


class IngestResult(BaseModel):
    """Result returned by ingestion services."""

    document: DocumentRecord
    chunks_indexed: int
    facts_extracted: int
    deltas_created: int
    neo4j_available: bool
    warnings: list[str] = Field(default_factory=list)


class QueryResult(BaseModel):
    """Evidence-verified query result."""

    query: str
    intent: str
    system_name: str | None = None
    version: str | None = None
    supported: bool
    answer: str
    facts: list[FactRecord] = Field(default_factory=list)
    chunks: list[ChunkRecord] = Field(default_factory=list)
    deltas: list[DeltaRecord] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
