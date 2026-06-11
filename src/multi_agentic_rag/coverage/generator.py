"""Deterministic coverage generation from requirement facts."""

from __future__ import annotations

from multi_agentic_rag.models import CoverageRecord, FactRecord
from multi_agentic_rag.utils.hashing import stable_id


def generate_requirement_coverage(requirement_facts: list[FactRecord]) -> list[CoverageRecord]:
    """Generate baseline coverage records only for facts with requirement links."""

    records: list[CoverageRecord] = []
    for fact in requirement_facts:
        requirement_id = fact.requirement_id or (
            fact.value if fact.fact_type == "requirement" else None
        )
        if not requirement_id:
            continue
        records.append(
            CoverageRecord(
                coverage_id=stable_id("coverage", requirement_id, fact.chunk_id),
                requirement_id=requirement_id,
                use_case=f"Validate requirement {requirement_id}",
                test_scenario=f"Confirm documented behavior for {requirement_id}",
                automation_feasibility="review_required",
                priority="medium",
                coverage_status="draft",
                evidence=[fact.evidence],
            )
        )
    return records
