"""Knowledge graph-oriented records."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from multi_agentic_rag.models.document import DocumentStatus


class RequirementRecord(BaseModel):
    """Requirement node metadata."""

    requirement_id: str
    document_id: str
    chunk_id: str
    system_name: str
    version: str
    status: DocumentStatus
    text: str


class EntityRecord(BaseModel):
    """Entity node metadata."""

    entity_id: str
    entity_type: str
    name: str
    document_id: str
    chunk_id: str
    system_name: str
    version: str
    status: DocumentStatus


class FactRecord(BaseModel):
    """Extracted fact with evidence lineage."""

    fact_id: str
    fact_key: str
    fact_type: str
    value: str
    document_id: str
    chunk_id: str
    system_name: str
    version: str
    status: DocumentStatus
    evidence: str
    unit: str | None = None
    requirement_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
