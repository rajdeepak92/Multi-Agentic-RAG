"""Coverage routes."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter

from multi_agentic_rag.coverage import DEFAULT_SCENARIO_COUNT, plan_requirement_coverage
from multi_agentic_rag.models import CoveragePlanResult

router = APIRouter(tags=["coverage"])


class CoverageRequest(BaseModel):
    """Coverage generation request."""

    system_name: str = Field(alias="system")
    version: str | None = None
    scenario_count: int = DEFAULT_SCENARIO_COUNT
    force: bool = False


@router.post("/coverage", response_model=CoveragePlanResult)
def coverage(request: CoverageRequest) -> CoveragePlanResult:
    return plan_requirement_coverage(
        system_name=request.system_name,
        version=request.version,
        scenario_count=request.scenario_count,
        force=request.force,
    )


@router.post("/coverage/plan", response_model=CoveragePlanResult)
def coverage_plan(request: CoverageRequest) -> CoveragePlanResult:
    return coverage(request)
