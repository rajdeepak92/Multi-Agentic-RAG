"""Pydantic contracts for version-aware RAG records."""

from multi_agentic_rag.models.chunk import ChunkRecord, build_chunk_id
from multi_agentic_rag.models.coverage import CoverageRecord
from multi_agentic_rag.models.delta import DeltaRecord
from multi_agentic_rag.models.document import DocumentRecord, DocumentStatus
from multi_agentic_rag.models.graph import EntityRecord, FactRecord, RequirementRecord
from multi_agentic_rag.models.output import EvidenceRecord, IngestResult, QueryResult

__all__ = [
    "ChunkRecord",
    "CoverageRecord",
    "DeltaRecord",
    "DocumentRecord",
    "DocumentStatus",
    "EntityRecord",
    "EvidenceRecord",
    "FactRecord",
    "IngestResult",
    "QueryResult",
    "RequirementRecord",
    "build_chunk_id",
]
