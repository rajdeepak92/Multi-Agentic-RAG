"""Tracked coverage planning services."""

from __future__ import annotations

from datetime import UTC, datetime

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.models import (
    CoveragePlanResult,
    CoverageRecord,
    CoverageRunRecord,
    DocumentRecord,
    DocumentStatus,
    FactRecord,
)
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.utils.hashing import stable_id

DEFAULT_SCENARIO_COUNT = 25

SCENARIO_TEMPLATES = (
    "Validate documented happy path behavior",
    "Validate boundary values and limits",
    "Validate missing or invalid input handling",
    "Validate protocol or interface behavior",
    "Validate traceability and audit evidence",
)


def plan_requirement_coverage(
    *,
    system_name: str,
    version: str | None = None,
    scenario_count: int = DEFAULT_SCENARIO_COUNT,
    force: bool = False,
    settings: Settings | None = None,
) -> CoveragePlanResult:
    """Create or reuse a requirement-linked coverage plan."""

    settings = settings or get_settings()
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    documents = _scope_documents(registry, system_name=system_name, version=version)
    if not documents:
        return CoveragePlanResult(
            supported=False,
            action="unsupported",
            message="No document evidence found for the requested system/version.",
        )
    facts = _scope_requirement_facts(registry, system_name=system_name, version=version)
    if not facts:
        return CoveragePlanResult(
            supported=False,
            action="unsupported",
            message="No requirement evidence found. No coverage claim can be made.",
        )

    scope_hash = _scope_hash(documents)
    existing = registry.find_coverage_run(
        system_name=system_name,
        version=version,
        scope_hash=scope_hash,
        scenario_count=scenario_count,
        status="completed",
    )
    if existing and not force:
        return CoveragePlanResult(
            supported=True,
            action="reused",
            message=(
                "Coverage already exists for this document scope. "
                "Reused existing records instead of regenerating."
            ),
            run=existing,
            records=registry.list_coverage_by_ids(existing.coverage_ids),
        )

    records = _build_coverage_records(
        facts=facts,
        documents=documents,
        scope_hash=scope_hash,
        scenario_count=scenario_count,
    )
    now = _utc_now()
    run = CoverageRunRecord(
        run_id=stable_id("coverage_run", system_name, version, scope_hash, scenario_count),
        system_name=system_name,
        version=version,
        scope_hash=scope_hash,
        scenario_count=scenario_count,
        status="completed",
        generated_count=len(records),
        coverage_ids=[record.coverage_id for record in records],
        message=f"Generated {len(records)} coverage scenario(s).",
        created_at=now,
        updated_at=now,
    )
    registry.upsert_coverage(records)
    registry.upsert_coverage_run(run)
    return CoveragePlanResult(
        supported=True,
        action="generated",
        message=run.message,
        run=run,
        records=records,
    )


def _scope_documents(
    registry: SQLiteRegistry,
    *,
    system_name: str,
    version: str | None,
) -> list[DocumentRecord]:
    if version:
        return [
            document
            for document in registry.list_documents(system_name=system_name)
            if document.version == version
        ]
    return registry.list_documents(system_name=system_name, status=DocumentStatus.ACTIVE)


def _scope_requirement_facts(
    registry: SQLiteRegistry,
    *,
    system_name: str,
    version: str | None,
) -> list[FactRecord]:
    facts = registry.list_facts(
        system_name=system_name,
        version=version,
        status=None if version else DocumentStatus.ACTIVE,
    )
    return [fact for fact in facts if fact.fact_type == "requirement"]


def _scope_hash(documents: list[DocumentRecord]) -> str:
    parts = [
        f"{document.document_id}:{document.version}:{document.content_hash}"
        for document in sorted(documents, key=lambda item: item.document_id)
    ]
    return stable_id("scope", *parts)


def _build_coverage_records(
    *,
    facts: list[FactRecord],
    documents: list[DocumentRecord],
    scope_hash: str,
    scenario_count: int,
) -> list[CoverageRecord]:
    document_by_id = {document.document_id: document for document in documents}
    records: list[CoverageRecord] = []
    for index in range(1, scenario_count + 1):
        fact = facts[(index - 1) % len(facts)]
        requirement_id = fact.requirement_id or fact.value
        template = SCENARIO_TEMPLATES[(index - 1) % len(SCENARIO_TEMPLATES)]
        document = document_by_id.get(fact.document_id)
        records.append(
            CoverageRecord(
                coverage_id=stable_id(
                    "coverage",
                    scope_hash,
                    requirement_id,
                    fact.chunk_id,
                    index,
                ),
                requirement_id=requirement_id,
                use_case=f"{template} for {requirement_id}",
                test_scenario=(
                    f"Scenario {index}: {template.lower()} using BRD evidence for "
                    f"{requirement_id}."
                ),
                automation_feasibility="review_required",
                priority="medium",
                coverage_status="draft",
                evidence=[fact.evidence],
                document_id=fact.document_id,
                version=fact.version,
                chunk_id=fact.chunk_id,
                scenario_index=index,
                source_hash=document.content_hash if document else None,
            )
        )
    return records


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
