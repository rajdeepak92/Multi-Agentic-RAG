"""Coverage models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CoverageRecord(BaseModel):
    """Requirement coverage output with traceable evidence."""

    coverage_id: str
    requirement_id: str
    use_case: str
    test_scenario: str
    automation_feasibility: str
    priority: str
    coverage_status: str
    evidence: list[str] = Field(default_factory=list)
