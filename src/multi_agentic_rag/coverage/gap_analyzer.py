"""Coverage gap analysis."""

from __future__ import annotations

from multi_agentic_rag.models import CoverageRecord, FactRecord


def find_uncovered_requirements(
    requirement_facts: list[FactRecord],
    coverage_records: list[CoverageRecord],
) -> list[str]:
    """Return requirement IDs that do not have coverage records."""

    covered = {record.requirement_id for record in coverage_records}
    requirements = {
        fact.requirement_id or fact.value
        for fact in requirement_facts
        if fact.fact_type == "requirement" and (fact.requirement_id or fact.value)
    }
    return sorted(requirements - covered)
