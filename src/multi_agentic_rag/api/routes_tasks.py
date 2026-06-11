"""Natural-language task route."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter

from multi_agentic_rag.coverage import DEFAULT_SCENARIO_COUNT
from multi_agentic_rag.models import TaskResult
from multi_agentic_rag.tasks import handle_task

router = APIRouter(tags=["tasks"])


class TaskRequest(BaseModel):
    """Natural-language task request."""

    request: str
    system_name: str = Field(alias="system")
    version: str | None = None
    scenario_count: int = DEFAULT_SCENARIO_COUNT


@router.post("/tasks", response_model=TaskResult)
def task(request: TaskRequest) -> TaskResult:
    return handle_task(
        request.request,
        system_name=request.system_name,
        version=request.version,
        scenario_count=request.scenario_count,
    )
