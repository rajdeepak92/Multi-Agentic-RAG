"""Pydantic contracts for version-aware RAG records."""

from multi_agentic_rag.models.chunk import ChunkRecord, build_chunk_id
from multi_agentic_rag.models.coverage import (
    CoverageRecord,
    CoverageRunRecord,
    GeneratedTestFileRecord,
    TestRunResultRecord,
)
from multi_agentic_rag.models.delta import DeltaRecord
from multi_agentic_rag.models.document import DocumentRecord, DocumentStatus
from multi_agentic_rag.models.graph import EntityRecord, FactRecord, RequirementRecord
from multi_agentic_rag.models.output import (
    AutomationTaskResult,
    CoveragePlanResult,
    EvidenceRecord,
    ExecutionSummary,
    GeneratedArtifacts,
    IngestResult,
    QueryResult,
    TaskResult,
    TestExecutionResult,
    TestGenerationResult,
)

__all__ = [
    "ChunkRecord",
    "CoverageRecord",
    "CoverageRunRecord",
    "CoveragePlanResult",
    "AutomationTaskResult",
    "DeltaRecord",
    "DocumentRecord",
    "DocumentStatus",
    "EntityRecord",
    "EvidenceRecord",
    "ExecutionSummary",
    "FactRecord",
    "GeneratedArtifacts",
    "GeneratedTestFileRecord",
    "IngestResult",
    "QueryResult",
    "RequirementRecord",
    "TaskResult",
    "TestExecutionResult",
    "TestGenerationResult",
    "TestRunResultRecord",
    "build_chunk_id",
]
