"""Domain records and DTOs."""

from multi_agentic_rag.domain.models import (
    ChunkRecord,
    DeltaRecord,
    DocumentInput,
    DocumentRecord,
    DocumentStatus,
    DocumentVersionRecord,
    EntityRecord,
    FactRecord,
    IngestionRunRecord,
    IngestionRunStatus,
    IngestResult,
    PageText,
    RequirementRecord,
    RetrievalResult,
    SystemRecord,
    build_chunk_id,
)

__all__ = [
    "ChunkRecord",
    "DeltaRecord",
    "DocumentInput",
    "DocumentRecord",
    "DocumentStatus",
    "DocumentVersionRecord",
    "EntityRecord",
    "FactRecord",
    "IngestionRunRecord",
    "IngestionRunStatus",
    "IngestResult",
    "PageText",
    "RequirementRecord",
    "RetrievalResult",
    "SystemRecord",
    "build_chunk_id",
]
