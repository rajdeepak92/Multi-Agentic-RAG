"""Delta routes."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter

from multi_agentic_rag.config import get_settings
from multi_agentic_rag.models import DeltaRecord
from multi_agentic_rag.storage.registry import select_registry

router = APIRouter(tags=["delta"])


class DeltaRequest(BaseModel):
    """Delta lookup request."""

    system_name: str = Field(alias="system")
    from_version: str | None = Field(default=None, alias="from")
    to_version: str | None = Field(default=None, alias="to")


@router.post("/delta", response_model=list[DeltaRecord])
def delta(request: DeltaRequest) -> list[DeltaRecord]:
    registry = select_registry(get_settings()).registry
    registry.initialize()
    return registry.list_deltas(
        system_name=request.system_name,
        from_version=request.from_version,
        to_version=request.to_version,
    )
