"""Document lineage models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    """Lifecycle status for versioned documents and derived evidence."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DRAFT = "draft"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class DocumentRecord(BaseModel):
    """Metadata record for a source document."""

    document_id: str
    system_name: str
    version: str
    status: DocumentStatus = DocumentStatus.ACTIVE
    source_path: str
    source_name: str
    content_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    supersedes: str | None = None
    superseded_by: str | None = None
