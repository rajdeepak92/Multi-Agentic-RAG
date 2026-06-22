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
    POSTGRES_COMMITTED = "postgres_committed"
    CHROMA_INDEXED = "chroma_indexed"
    NEO4J_PROJECTED = "neo4j_projected"
    COMPLETED = "completed"
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
        status: Stage checkpoint for this ingestion run.
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
        bm25_status: PostgreSQL lexical-readiness status string.
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


class GraphMatch(BaseModel):
    """One graph traversal hit used to hydrate and explain retrieval evidence."""

    chunk_id: str
    score: float
    reason: str
    path: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)


class RankedRetrievalResult(RetrievalResult):
    """Retrieval result with deterministic rank and trace metadata.

    Attributes:
        rank: One-based rank after fusion and optional reranking.
        evidence_path: Human-readable lineage path from system to chunk.
    """

    rank: int
    evidence_path: list[str] = Field(default_factory=list)


class TaskIntentType(StrEnum):
    """High-level task intents supported by the workflow router."""

    ANSWER_QUERY = "answer_query"
    INGEST_DOCUMENT = "ingest_document"
    BUILD_USER_STORIES = "build_user_stories"
    INGEST_THEN_BUILD_USER_STORIES = "ingest_then_build_user_stories"
    TEST_SCENARIO_GENERATION = "test_scenario_generation"
    TEST_CASE_WRITING = "test_case_writing"
    TEST_CASE_EXECUTION = "test_case_execution"
    COVERAGE_GENERATION = "coverage_generation"


class AgentRunStatus(StrEnum):
    """High-level agent execution status."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    REFUSED = "refused"


class WorkflowStatus(StrEnum):
    """Workflow run status."""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskIntent(BaseModel):
    """Structured natural-language task classification.

    Attributes:
        intent_type: High-level task class selected by the router.
        system: System namespace required for document-scoped work.
        kb: Knowledge-base namespace.
        version: Optional document version scope.
        documents: Source document paths extracted from the request.
        output_request: Requested output type or destination.
        missing_slots: Required fields that could not be inferred.
        confidence: Router confidence from 0.0 to 1.0.
    """

    intent_type: TaskIntentType
    system: str | None = None
    kb: str = "default"
    version: str | None = None
    documents: list[str] = Field(default_factory=list)
    output_request: str | None = None
    missing_slots: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class WorkflowPlan(BaseModel):
    """Ordered high-level plan executed by the LangGraph workflow."""

    ordered_agents: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    """Validated evidence passed to OpenAI for generation or synthesis."""

    query: str
    ranked_results: list[RankedRetrievalResult] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(default_factory=list)
    graph_paths: list[list[str]] = Field(default_factory=list)
    version_scope: str | None = None


class QualityValidationReport(BaseModel):
    """Validation result for handoffs, generated artifacts, or model outputs."""

    status: Literal["passed", "failed"]
    messages: list[str] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)


class GroundedAnswer(BaseModel):
    """OpenAI-synthesized answer constrained to supplied evidence."""

    answer: str
    refused: bool = False
    citations: list[str] = Field(default_factory=list)
    validation_status: Literal["passed", "failed"] = "passed"


class GeneratedUserStory(BaseModel):
    """Generated user-story YAML contract.

    Field names intentionally match the required YAML template.
    """

    id: str
    title: str
    type: str
    domain: str
    priority: str
    status: str
    persona: str
    user_story: str
    business_value: str
    description: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    non_functional_requirements: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    definition_of_ready: list[str] = Field(default_factory=list)
    definition_of_done: list[str] = Field(default_factory=list)
    traceability: dict[str, Any] = Field(default_factory=dict)


class GeneratedUserStoryBatch(BaseModel):
    """Structured OpenAI output for one user-story generation pass."""

    stories: list[GeneratedUserStory] = Field(default_factory=list)
    reasoning_summary: str = ""


class FactSplitSuggestion(BaseModel):
    """One proposed split extracted from a mixed fact."""

    fact_type: str
    canonical_name: str | None = None
    value: str | None = None
    relationship_hint: str | None = None
    notes: str = ""


class FactEnrichmentSuggestion(BaseModel):
    """LLM suggestion for one ambiguous deterministic fact."""

    fact_id: str
    fact_key: str
    review_status: Literal["validated", "flagged"]
    canonical_name: str | None = None
    relationship_hint: str | None = None
    split_candidates: list[FactSplitSuggestion] = Field(default_factory=list)
    uncertain_relationships: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning_summary: str = ""


class FactEnrichmentBatch(BaseModel):
    """Structured OpenAI output for ingest-time fact review."""

    suggestions: list[FactEnrichmentSuggestion] = Field(default_factory=list)
    reasoning_summary: str = ""


class ArtifactManifest(BaseModel):
    """Manifest for a generated local artifact and its debug trace."""

    artifact_id: str
    story_id: str | None = None
    generated_file_path: str
    debug_json_path: str
    source_chunk_ids: list[str] = Field(default_factory=list)
    model: str
    prompt_version: str
    validation_status: Literal["passed", "failed"]


class AgentRunResult(BaseModel):
    """Result returned by standalone high-level agents."""

    status: AgentRunStatus
    messages: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    next_suggested_task: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowState(BaseModel):
    """LangGraph workflow state exchanged between graph nodes."""

    workflow_run_id: str
    request: str
    default_system: str | None = None
    default_kb: str = "default"
    default_version: str | None = None
    default_documents: list[str] = Field(default_factory=list)
    current_step: str = "intake"
    intent: TaskIntent | None = None
    plan: WorkflowPlan | None = None
    selected_agents: list[str] = Field(default_factory=list)
    evidence_bundles: list[EvidenceBundle] = Field(default_factory=list)
    artifacts: list[ArtifactManifest] = Field(default_factory=list)
    validation_reports: list[QualityValidationReport] = Field(default_factory=list)
    agent_results: list[AgentRunResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    final_response: str | None = None
    status: WorkflowStatus = WorkflowStatus.STARTED


class WorkflowRunRecord(BaseModel):
    """Audit record for one LangGraph workflow run."""

    workflow_run_id: str
    system_name: str | None = None
    kb_name: str = "default"
    version: str | None = None
    request: str
    intent_type: str | None = None
    status: WorkflowStatus
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepRecord(BaseModel):
    """Audit record for one high-level workflow step."""

    workflow_step_id: str
    workflow_run_id: str
    step_index: int
    agent_name: str
    status: AgentRunStatus
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    messages: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactRecord(BaseModel):
    """PostgreSQL audit record for generated files."""

    artifact_id: str
    workflow_run_id: str | None = None
    system_name: str
    kb_name: str
    version: str
    artifact_type: str
    artifact_path: str
    debug_json_path: str | None = None
    source_chunk_ids: list[str] = Field(default_factory=list)
    model: str
    prompt_version: str
    validation_status: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalFactRecord(BaseModel):
    """Current semantic fact tracked across document versions."""

    canonical_fact_id: str
    system_name: str
    kb_name: str
    semantic_key: str
    current_value: str
    status: Literal["active", "superseded", "removed"] = "active"
    originating_fact_id: str
    active_fact_id: str
    originating_version_id: str
    last_confirmed_version_id: str
    superseded_by_fact_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning_summary: str = "deterministic extraction"
