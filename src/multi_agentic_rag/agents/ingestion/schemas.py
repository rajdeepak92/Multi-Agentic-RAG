"""Public schemas for knowledge-base ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from multi_agentic_rag.domain import IngestResult


class IngestionRequest(BaseModel):
    """Input required to ingest one versioned document."""

    document_path: Path
    system: str
    version: str
    kb: str = "default"


class IngestionResult(BaseModel):
    """LangGraph ingestion result wrapper."""

    status: Literal["succeeded", "failed"]
    ingest_result: IngestResult | None = None
    run_id: str | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
