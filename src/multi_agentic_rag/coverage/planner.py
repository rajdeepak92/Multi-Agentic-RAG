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
from multi_agentic_rag.retrieval.graph_retriever import GraphRetriever
from multi_agentic_rag.storage.registry import Registry, select_registry
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
    registry = select_registry(settings).registry
    registry.initialize()
    documents = _scope_documents(registry, system_name=system_name, version=version)
    if not documents:
        return CoveragePlanResult(
            supported=False,
            action="unsupported",
            message="No document evidence found for the requested system/version.",
        )
    registry_facts = _scope_requirement_facts(registry, system_name=system_name, version=version)
    if not registry_facts:
        return CoveragePlanResult(
            supported=False,
            action="unsupported",
            message="No requirement evidence found. No coverage claim can be made.",
        )
    warnings: list[str] = []
    facts, graph_warning, planning_source = _select_planning_facts(
        facts=registry_facts,
        settings=settings,
        system_name=system_name,
        version=version,
    )
    if graph_warning:
        if _target_graphrag_required(settings):
            return CoveragePlanResult(
                supported=False,
                action="unsupported",
                message=graph_warning,
                warnings=[graph_warning],
            )
        warnings.append(graph_warning)

    scope_hash = _scope_hash(documents, facts=facts, planning_source=planning_source)
    existing = registry.find_coverage_run(
        system_name=system_name,
        version=version,
        scope_hash=scope_hash,
        scenario_count=scenario_count,
        status="completed",
    )
    message_suffix = _planning_source_message(planning_source)
    if existing and not force:
        return CoveragePlanResult(
            supported=True,
            action="reused",
            message=(
                "Coverage already exists for this document scope. "
                f"Reused existing records instead of regenerating. {message_suffix}"
            ),
            run=existing,
            records=registry.list_coverage_by_ids(existing.coverage_ids),
            warnings=warnings,
        )

    records = _build_coverage_records(
        facts=facts,
        documents=documents,
        scope_hash=scope_hash,
        scenario_count=scenario_count,
        impact_by_key=_version_impact_by_key(
            registry=registry,
            system_name=system_name,
            version=version,
        ),
        previous_by_key=_previous_coverage_by_semantic_key(
            registry=registry,
            version=version,
        ),
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
        message=f"Generated {len(records)} coverage scenario(s). {message_suffix}",
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
        warnings=warnings,
    )


def _scope_documents(
    registry: Registry,
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
    registry: Registry,
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


def _scope_hash(
    documents: list[DocumentRecord],
    *,
    facts: list[FactRecord],
    planning_source: str,
) -> str:
    parts = [
        f"{document.document_id}:{document.version}:{document.content_hash}"
        for document in sorted(documents, key=lambda item: item.document_id)
    ]
    parts.append(f"planning_source:{planning_source}")
    parts.extend(
        f"fact:{fact.fact_id}:{fact.semantic_key or fact.fact_key}"
        for fact in sorted(facts, key=lambda item: item.fact_id)
    )
    return stable_id("scope", *parts)


def _build_coverage_records(
    *,
    facts: list[FactRecord],
    documents: list[DocumentRecord],
    scope_hash: str,
    scenario_count: int,
    impact_by_key: dict[str, str],
    previous_by_key: dict[str, CoverageRecord],
) -> list[CoverageRecord]:
    document_by_id = {document.document_id: document for document in documents}
    records: list[CoverageRecord] = []
    for index in range(1, scenario_count + 1):
        fact = facts[(index - 1) % len(facts)]
        requirement_id = fact.requirement_id or fact.value
        semantic_key = fact.semantic_key or fact.fact_key
        previous = previous_by_key.get(semantic_key)
        impact_status = impact_by_key.get(semantic_key)
        if not impact_status:
            impact_status = "unchanged" if previous else "new_required"
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
                coverage_status="reused" if impact_status == "unchanged" else "draft",
                evidence=[fact.evidence],
                document_id=fact.document_id,
                version=fact.version,
                chunk_id=fact.chunk_id,
                fact_id=fact.fact_id,
                semantic_key=semantic_key,
                impact_status=impact_status,
                previous_coverage_id=previous.coverage_id if previous else None,
                scenario_index=index,
                source_hash=document.content_hash if document else None,
            )
        )
    return records


def _version_impact_by_key(
    *,
    registry: Registry,
    system_name: str,
    version: str | None,
) -> dict[str, str]:
    if not version:
        return {}
    impact_by_change = {
        "added": "new_required",
        "modified": "needs_data_update",
        "removed": "superseded",
    }
    impacts: dict[str, str] = {}
    for delta in registry.list_deltas(system_name=system_name, to_version=version):
        if delta.fact_key:
            impacts[delta.fact_key] = impact_by_change.get(delta.change_type, delta.change_type)
    return impacts


def _previous_coverage_by_semantic_key(
    *,
    registry: Registry,
    version: str | None,
) -> dict[str, CoverageRecord]:
    previous: dict[str, CoverageRecord] = {}
    for record in registry.list_coverage():
        if not record.semantic_key or record.version == version:
            continue
        if record.lifecycle_status != "active":
            continue
        previous.setdefault(record.semantic_key, record)
    return previous


def _select_planning_facts(
    *,
    facts: list[FactRecord],
    settings: Settings,
    system_name: str,
    version: str | None,
) -> tuple[list[FactRecord], str | None, str]:
    if not system_name:
        return facts, None, "sqlite_registry_fallback"
    retriever = GraphRetriever(settings)
    if version:
        result = retriever.get_facts_by_version(system_name, version)
    else:
        result = retriever.get_current_facts(system_name)
    if result.warning:
        return (
            facts,
            f"Graph-backed scenario selection unavailable: {result.warning}",
            "sqlite_registry_fallback",
        )
    graph_fact_ids = _ordered_graph_requirement_fact_ids(result.records)
    if not graph_fact_ids:
        message = "Graph-backed scenario selection unavailable: no requirement facts in Neo4j."
        return facts, message if _target_graphrag_required(settings) else None, "sqlite_registry_fallback"
    facts_by_id = {fact.fact_id: fact for fact in facts}
    selected = [facts_by_id[fact_id] for fact_id in graph_fact_ids if fact_id in facts_by_id]
    if not selected:
        message = (
            "Graph-backed scenario selection unavailable: Neo4j requirement facts "
            "did not match registry evidence."
        )
        return facts, message if _target_graphrag_required(settings) else message, "sqlite_registry_fallback"
    missing_count = len(graph_fact_ids) - len(selected)
    warning = None
    if missing_count:
        warning = (
            "Graph-backed scenario selection used Neo4j, but "
            f"{missing_count} graph requirement fact(s) were missing registry evidence."
        )
    return selected, warning, "neo4j_graph"


def _ordered_graph_requirement_fact_ids(records: list[dict[str, object]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for record in records:
        if record.get("fact_type") != "requirement":
            continue
        fact_id = str(record.get("fact_id") or "").strip()
        if not fact_id or fact_id in seen:
            continue
        seen.add(fact_id)
        ordered.append(fact_id)
    return ordered


def _planning_source_message(planning_source: str) -> str:
    if planning_source == "neo4j_graph":
        return "Scenario selection used Neo4j graph-backed requirement evidence."
    return "Scenario selection used SQLite registry fallback because graph-backed evidence was unavailable."


def _target_graphrag_required(settings: Settings) -> bool:
    return settings.marag_target_mode == "target-graphrag" or settings.graphrag_required


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
