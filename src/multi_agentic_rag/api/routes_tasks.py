"""Natural-language task route."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

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
    mock: bool = False
    execution_mode: str | None = None


@router.post("/tasks", response_model=TaskResult)
def task(request: TaskRequest) -> TaskResult:
    return handle_task(
        request.request,
        system_name=request.system_name,
        version=request.version,
        scenario_count=request.scenario_count,
        execution_mode=_execution_mode(request),
    )


def _execution_mode(request: TaskRequest) -> str | None:
    if request.mock:
        return "mock"
    if request.execution_mode:
        mode = request.execution_mode.strip().lower()
        if mode not in {"mock", "simulator", "real", "auto"}:
            raise HTTPException(
                status_code=422,
                detail="execution_mode must be mock, simulator, real, or auto",
            )
        return mode
    return None
