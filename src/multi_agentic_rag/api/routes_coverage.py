"""Coverage routes."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter

from multi_agentic_rag.config import get_settings
from multi_agentic_rag.coverage import generate_requirement_coverage
from multi_agentic_rag.models import CoverageRecord, DocumentStatus
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry

router = APIRouter(tags=["coverage"])


class CoverageRequest(BaseModel):
    """Coverage generation request."""

    system_name: str = Field(alias="system")


@router.post("/coverage", response_model=list[CoverageRecord])
def coverage(request: CoverageRequest) -> list[CoverageRecord]:
    registry = SQLiteRegistry(get_settings().sqlite_db_path)
    registry.initialize()
    requirement_facts = [
        fact
        for fact in registry.list_facts(
            system_name=request.system_name,
            status=DocumentStatus.ACTIVE,
        )
        if fact.fact_type == "requirement"
    ]
    records = generate_requirement_coverage(requirement_facts)
    registry.upsert_coverage(records)
    return records
