"""Structured output contracts for API/CLI responses."""

from __future__ import annotations

from pydantic import BaseModel, Field

from multi_agentic_rag.models.chunk import ChunkRecord
from multi_agentic_rag.models.coverage import (
    CoverageRecord,
    CoverageRunRecord,
    GeneratedTestFileRecord,
    TestRunResultRecord,
)
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
    vector_store: str = "chroma"
    keyword_indexed: int = 0
    object_store_path: str | None = None
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
    retrieval_sources: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CoveragePlanResult(BaseModel):
    """Result of creating or reusing a coverage plan."""

    supported: bool
    action: str
    message: str
    run: CoverageRunRecord | None = None
    records: list[CoverageRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TestGenerationResult(BaseModel):
    """Result of writing or reusing a generated testcase file."""

    supported: bool
    action: str
    message: str
    coverage: CoveragePlanResult | None = None
    test_file: GeneratedTestFileRecord | None = None
    tracking_file_path: str | None = None
    harness_file_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TestExecutionResult(BaseModel):
    """Result of executing generated testcases."""

    supported: bool
    action: str
    message: str
    test_file: GeneratedTestFileRecord | None = None
    result: TestRunResultRecord | None = None
    tracking_file_path: str | None = None
    attempts: int = 0
    warnings: list[str] = Field(default_factory=list)


class GeneratedArtifacts(BaseModel):
    """Artifact paths produced by an automation task."""

    pytest_files: list[str] = Field(default_factory=list)
    robot_files: list[str] = Field(default_factory=list)
    json_sidecars: list[str] = Field(default_factory=list)
    xml_reports: list[str] = Field(default_factory=list)
    coverage_reports: list[str] = Field(default_factory=list)
    reports: list[str] = Field(default_factory=list)


class ExecutionSummary(BaseModel):
    """Aggregated execution and reuse counts."""

    executed: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    blocked: int = 0
    skipped_unchanged: int = 0
    reused_from_previous_version: int = 0


class AutomationTaskResult(BaseModel):
    """Final router validation result for end-to-end QA automation requests."""

    request_status: str = "unknown"
    interpreted_intent: str = "unknown"
    document_path: str | None = None
    document_id: str | None = None
    document_version: str | None = None
    active_version: str | None = None
    superseded_versions: list[str] = Field(default_factory=list)
    generated_artifacts: GeneratedArtifacts = Field(default_factory=GeneratedArtifacts)
    affected_tests: list[str] = Field(default_factory=list)
    reused_tests: list[str] = Field(default_factory=list)
    skipped_unchanged_tests: list[str] = Field(default_factory=list)
    blocked_tests: list[str] = Field(default_factory=list)
    failed_tests: list[str] = Field(default_factory=list)
    execution_summary: ExecutionSummary = Field(default_factory=ExecutionSummary)
    db_update_status: str = "unknown"
    final_validation_status: str = "unknown"
    failure_reason: str | None = None


class TaskResult(BaseModel):
    """Natural-language task router result."""

    supported: bool
    intent: str
    message: str
    query: QueryResult | None = None
    coverage: CoveragePlanResult | None = None
    test_generation: TestGenerationResult | None = None
    test_execution: TestExecutionResult | None = None
    last_result: TestRunResultRecord | None = None
    automation: AutomationTaskResult | None = None
    warnings: list[str] = Field(default_factory=list)
