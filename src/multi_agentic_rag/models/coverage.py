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
    document_id: str | None = None
    version: str | None = None
    chunk_id: str | None = None
    scenario_index: int | None = None
    source_hash: str | None = None


class CoverageRunRecord(BaseModel):
    """Tracked coverage generation run for idempotent reuse."""

    run_id: str
    system_name: str
    version: str | None = None
    scope_hash: str
    scenario_count: int
    status: str
    generated_count: int
    coverage_ids: list[str] = Field(default_factory=list)
    message: str = ""
    created_at: str
    updated_at: str


class GeneratedTestFileRecord(BaseModel):
    """Generated pytest file linked to a coverage run."""

    test_file_id: str
    run_id: str
    system_name: str
    version: str | None = None
    scope_hash: str
    file_path: str
    tracking_file_path: str | None = None
    harness_file_paths: list[str] = Field(default_factory=list)
    status: str
    coverage_ids: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class TestRunResultRecord(BaseModel):
    """Stored result of executing a generated pytest file."""

    result_id: str
    test_file_id: str
    run_id: str
    system_name: str
    version: str | None = None
    file_path: str
    status: str
    exit_code: int | None = None
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failure_category: str | None = None
    failure_reason: str | None = None
    dependency_blockers: list[str] = Field(default_factory=list)
    output: str = ""
    created_at: str
