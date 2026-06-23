# mypy: ignore-errors
"""SQLAlchemy ORM models for the GraphRAG schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base."""


class SystemModel(Base):
    """Known product or application system that owns one or more knowledge bases."""

    __tablename__ = "systems"

    system_id: Mapped[str] = mapped_column(String, primary_key=True)
    system_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class DocumentModel(Base):
    """Stable document lineage independent of a specific source version."""

    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(String, primary_key=True)
    system_name: Mapped[str] = mapped_column(
        String, ForeignKey("systems.system_name"), nullable=False
    )
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    document_type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    __table_args__ = (
        UniqueConstraint("system_name", "kb_name", "source_name", name="uq_document_lineage"),
    )


class DocumentVersionModel(Base):
    """Immutable source version with status and supersession metadata."""

    __tablename__ = "document_versions"

    document_version_id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.document_id"), nullable=False
    )
    system_name: Mapped[str] = mapped_column(String, nullable=False)
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    supersedes_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    superseded_by_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    optimistic_lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    __table_args__ = (
        UniqueConstraint("document_id", "version", "content_hash", name="uq_document_version_hash"),
        Index("idx_document_versions_active", "system_name", "kb_name", "status"),
    )


class ChunkModel(Base):
    """Searchable text chunk associated with exactly one document version."""

    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(String, primary_key=True)
    document_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("document_versions.document_version_id"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(String, nullable=False)
    system_name: Mapped[str] = mapped_column(String, nullable=False)
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    section_title: Mapped[str | None] = mapped_column(String, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    __table_args__ = (
        Index("idx_chunks_document_version", "document_version_id"),
        Index("idx_chunks_system_status", "system_name", "kb_name", "status"),
    )


class FactModel(Base):
    """Extracted evidence fact anchored to the chunk that supports it."""

    __tablename__ = "facts"

    fact_id: Mapped[str] = mapped_column(String, primary_key=True)
    fact_key: Mapped[str] = mapped_column(String, nullable=False)
    fact_type: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    document_version_id: Mapped[str] = mapped_column(String, nullable=False)
    document_id: Mapped[str] = mapped_column(String, nullable=False)
    chunk_id: Mapped[str] = mapped_column(String, ForeignKey("chunks.chunk_id"), nullable=False)
    system_name: Mapped[str] = mapped_column(String, nullable=False)
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_id: Mapped[str | None] = mapped_column(String, nullable=True)
    semantic_key: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    __table_args__ = (
        Index("idx_facts_system_status", "system_name", "kb_name", "status"),
        Index("idx_facts_key", "fact_key"),
        Index("idx_facts_version", "document_version_id"),
    )


class RequirementModel(Base):
    """Canonical requirement ledger row with primary evidence linkage."""

    __tablename__ = "requirements"

    requirement_pk: Mapped[str] = mapped_column(String, primary_key=True)
    canonical_id: Mapped[str | None] = mapped_column(String, nullable=True)
    requirement_id: Mapped[str] = mapped_column(String, nullable=False)
    requirement_type: Mapped[str] = mapped_column(String, nullable=False, default="functional")
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    document_version_id: Mapped[str] = mapped_column(String, nullable=False)
    document_id: Mapped[str] = mapped_column(String, nullable=False)
    chunk_id: Mapped[str] = mapped_column(String, nullable=False)
    system_name: Mapped[str] = mapped_column(String, nullable=False)
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_name: Mapped[str | None] = mapped_column(String, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String, nullable=True)
    story_driving: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    coverage_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    extraction_method: Mapped[str] = mapped_column(String, nullable=False, default="deterministic")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    semantic_key: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "system_name",
            "kb_name",
            "requirement_id",
            "document_version_id",
            name="uq_requirement_version",
        ),
        Index(
            "idx_requirements_scope_type",
            "system_name",
            "kb_name",
            "version",
            "requirement_type",
        ),
        Index("idx_requirements_canonical", "system_name", "kb_name", "version", "canonical_id"),
    )


class RequirementEvidenceModel(Base):
    """One source span supporting a canonical requirement ledger row."""

    __tablename__ = "requirement_evidence"

    requirement_evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    requirement_pk: Mapped[str] = mapped_column(
        String, ForeignKey("requirements.requirement_pk"), nullable=False
    )
    chunk_id: Mapped[str] = mapped_column(String, ForeignKey("chunks.chunk_id"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("document_versions.document_version_id"), nullable=False
    )
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    section_title: Mapped[str | None] = mapped_column(String, nullable=True)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String, nullable=False, default="deterministic")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "requirement_pk",
            "chunk_id",
            "start_offset",
            "end_offset",
            name="uq_requirement_evidence_span",
        ),
        Index("idx_requirement_evidence_requirement", "requirement_pk"),
        Index("idx_requirement_evidence_version", "document_version_id"),
    )


class RequirementCoverageModel(Base):
    """Generated user-story coverage state for one requirement."""

    __tablename__ = "requirement_coverage"

    coverage_id: Mapped[str] = mapped_column(String, primary_key=True)
    requirement_pk: Mapped[str] = mapped_column(
        String, ForeignKey("requirements.requirement_pk"), nullable=False
    )
    canonical_id: Mapped[str] = mapped_column(String, nullable=False)
    story_id: Mapped[str | None] = mapped_column(String, nullable=True)
    coverage_status: Mapped[str] = mapped_column(String, nullable=False)
    deferred_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    source_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_pages: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "requirement_pk",
            "story_id",
            name="uq_requirement_coverage_story",
        ),
        Index("idx_requirement_coverage_status", "coverage_status"),
    )


class EntityModel(Base):
    """Named graph/search entity derived from extracted facts."""

    __tablename__ = "entities"

    entity_id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    document_version_id: Mapped[str] = mapped_column(String, nullable=False)
    document_id: Mapped[str] = mapped_column(String, nullable=False)
    chunk_id: Mapped[str] = mapped_column(String, nullable=False)
    system_name: Mapped[str] = mapped_column(String, nullable=False)
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class DeltaModel(Base):
    """Fact-level change between an older and newer document version."""

    __tablename__ = "deltas"

    delta_id: Mapped[str] = mapped_column(String, primary_key=True)
    system_name: Mapped[str] = mapped_column(String, nullable=False)
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    from_document_version_id: Mapped[str] = mapped_column(String, nullable=False)
    to_document_version_id: Mapped[str] = mapped_column(String, nullable=False)
    from_version: Mapped[str] = mapped_column(String, nullable=False)
    to_version: Mapped[str] = mapped_column(String, nullable=False)
    fact_key: Mapped[str | None] = mapped_column(String, nullable=True)
    change_type: Mapped[str] = mapped_column(String, nullable=False)
    change_magnitude: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_requirement_id: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        Index("idx_deltas_versions", "system_name", "kb_name", "from_version", "to_version"),
    )


class IngestionRunModel(Base):
    """Operational record for one ingestion attempt and its final status."""

    __tablename__ = "ingestion_runs"

    ingestion_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    system_name: Mapped[str] = mapped_column(String, nullable=False)
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    document_id: Mapped[str | None] = mapped_column(String, nullable=True)
    document_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class WorkflowRunModel(Base):
    """Operational record for one LangGraph workflow run."""

    __tablename__ = "workflow_runs"

    workflow_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    system_name: Mapped[str | None] = mapped_column(String, nullable=True)
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str | None] = mapped_column(String, nullable=True)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    intent_type: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    __table_args__ = (Index("idx_workflow_runs_scope", "system_name", "kb_name", "version"),)


class WorkflowStepModel(Base):
    """Operational record for one high-level workflow step."""

    __tablename__ = "workflow_steps"

    workflow_step_id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_run_id: Mapped[str] = mapped_column(
        String, ForeignKey("workflow_runs.workflow_run_id"), nullable=False
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    messages: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    artifact_paths: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    __table_args__ = (Index("idx_workflow_steps_run", "workflow_run_id", "step_index"),)


class ArtifactRecordModel(Base):
    """Audit record for generated local artifacts."""

    __tablename__ = "artifact_records"

    artifact_id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    system_name: Mapped[str] = mapped_column(String, nullable=False)
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String, nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    debug_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    validation_status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    __table_args__ = (
        Index("idx_artifact_records_scope", "system_name", "kb_name", "version"),
    )


class CanonicalFactModel(Base):
    """Current semantic fact state carried across source versions."""

    __tablename__ = "canonical_facts"

    canonical_fact_id: Mapped[str] = mapped_column(String, primary_key=True)
    system_name: Mapped[str] = mapped_column(String, nullable=False)
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    semantic_key: Mapped[str] = mapped_column(String, nullable=False)
    current_value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    originating_fact_id: Mapped[str] = mapped_column(String, nullable=False)
    active_fact_id: Mapped[str] = mapped_column(String, nullable=False)
    originating_version_id: Mapped[str] = mapped_column(String, nullable=False)
    last_confirmed_version_id: Mapped[str] = mapped_column(String, nullable=False)
    superseded_by_fact_id: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float] = mapped_column(nullable=False, default=1.0)
    reasoning_summary: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "system_name",
            "kb_name",
            "semantic_key",
            name="uq_canonical_fact_semantic_key",
        ),
        Index("idx_canonical_facts_active", "system_name", "kb_name", "status"),
    )


class RetrievalMetadataModel(Base):
    """Auxiliary metadata used to inspect and filter retrieval results."""

    __tablename__ = "retrieval_metadata"

    retrieval_metadata_id: Mapped[str] = mapped_column(String, primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String, nullable=False)
    document_version_id: Mapped[str] = mapped_column(String, nullable=False)
    system_name: Mapped[str] = mapped_column(String, nullable=False)
    kb_name: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
