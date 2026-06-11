"""Generated testcase routes."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter

from multi_agentic_rag.coverage import DEFAULT_SCENARIO_COUNT
from multi_agentic_rag.models import TestExecutionResult, TestGenerationResult
from multi_agentic_rag.testing import generate_testcases, get_last_test_result, run_testcases

router = APIRouter(prefix="/tests", tags=["tests"])


class TestcaseRequest(BaseModel):
    """Request for testcase generation or execution."""

    system_name: str = Field(alias="system")
    version: str | None = None
    scenario_count: int = DEFAULT_SCENARIO_COUNT
    force: bool = False


@router.post("/generate", response_model=TestGenerationResult)
def generate(request: TestcaseRequest) -> TestGenerationResult:
    return generate_testcases(
        system_name=request.system_name,
        version=request.version,
        scenario_count=request.scenario_count,
        force=request.force,
    )


@router.post("/run", response_model=TestExecutionResult)
def run(request: TestcaseRequest) -> TestExecutionResult:
    return run_testcases(
        system_name=request.system_name,
        version=request.version,
        scenario_count=request.scenario_count,
    )


@router.post("/last-result", response_model=TestExecutionResult)
def last_result(request: TestcaseRequest) -> TestExecutionResult:
    return get_last_test_result(system_name=request.system_name, version=request.version)
