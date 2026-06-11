"""Document ingestion routes."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter

from multi_agentic_rag.ingestion import ingest_document
from multi_agentic_rag.models import IngestResult

router = APIRouter(prefix="/documents", tags=["documents"])


class IngestDocumentRequest(BaseModel):
    """Local document ingest request."""

    path: str = Field(description="Local path to a PDF document.")
    system_name: str = Field(alias="system")
    version: str


@router.post("/ingest", response_model=IngestResult)
def ingest(request: IngestDocumentRequest) -> IngestResult:
    return ingest_document(
        request.path,
        system_name=request.system_name,
        version=request.version,
    )
