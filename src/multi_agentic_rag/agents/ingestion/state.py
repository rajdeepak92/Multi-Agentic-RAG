"""Typed state for the ingestion LangGraph."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from multi_agentic_rag.agents.ingestion.schemas import IngestionRequest, IngestionResult
from multi_agentic_rag.common import IngestionStage
from multi_agentic_rag.config import RuntimePaths
from multi_agentic_rag.domain import (
    ChunkRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    DocumentVersionRecord,
    FactRecord,
    IngestResult,
    PageText,
    RequirementDiscoveryResult,
    RequirementEvidenceRecord,
    RequirementRecord,
    ReviewEventRecord,
    SourceSegmentRecord,
)


class IngestionState(TypedDict, total=False):
    """State exchanged between ingestion graph nodes."""

    request: IngestionRequest
    run_id: str
    source_path: Path
    source_hash: str
    runtime_paths: RuntimePaths
    requested_version: str
    effective_version: str
    previous_document_version: DocumentVersionRecord | None
    previous_document_id: str | None
    document_id: str
    document: DocumentRecord
    document_version: DocumentVersionRecord
    document_status: DocumentStatus
    managed_source: Path
    pages: list[PageText]
    segments: list[SourceSegmentRecord]
    chunks: list[ChunkRecord]
    old_chunks: list[ChunkRecord]
    facts: list[FactRecord]
    old_facts: list[FactRecord]
    requirements: list[RequirementRecord]
    requirement_evidence: list[RequirementEvidenceRecord]
    requirement_discovery: RequirementDiscoveryResult
    deltas: list[DeltaRecord]
    supersedes_version_id: str | None
    manifest_path: Path
    postgres_status: str
    chroma_status: str
    neo4j_status: str
    bm25_status: str
    run_started: bool
    stage: IngestionStage
    result: IngestionResult
    ingest_result: IngestResult
    errors: list[str]
    warnings: list[str]
    review_events: list[ReviewEventRecord]
    metadata: dict[str, Any]
