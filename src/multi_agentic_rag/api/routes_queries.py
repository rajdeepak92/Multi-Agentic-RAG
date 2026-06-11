"""Query routes."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

from multi_agentic_rag.models import QueryResult
from multi_agentic_rag.retrieval import answer_query

router = APIRouter(tags=["queries"])


class QueryRequest(BaseModel):
    """Evidence query request."""

    query: str
    system_name: str | None = None
    version: str | None = None


@router.post("/query", response_model=QueryResult)
def query(request: QueryRequest) -> QueryResult:
    return answer_query(
        request.query,
        system_name=request.system_name,
        version=request.version,
    )
