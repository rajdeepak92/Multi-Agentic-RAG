"""Evidence-verified hybrid retrieval facade."""

from __future__ import annotations

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.models import ChunkRecord, DocumentStatus, EvidenceRecord, QueryResult
from multi_agentic_rag.models.graph import FactRecord
from multi_agentic_rag.retrieval.graph_retriever import GraphRetriever
from multi_agentic_rag.retrieval.intent import QueryIntent, detect_intent
from multi_agentic_rag.retrieval.keyword_retriever import KeywordRetriever
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.storage.vector_factory import select_vector_store


def answer_query(
    query: str,
    *,
    system_name: str | None = None,
    version: str | None = None,
    settings: Settings | None = None,
) -> QueryResult:
    """Return a deterministic answer only when evidence exists."""

    settings = settings or get_settings()
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    intent = detect_intent(query)

    if intent == QueryIntent.DELTA_ANALYSIS:
        return _answer_delta_query(
            query=query,
            system_name=system_name,
            settings=settings,
            intent=intent,
        )
    if intent == QueryIntent.COVERAGE_GENERATION:
        return _answer_coverage_query(
            query=query,
            system_name=system_name,
            settings=settings,
            intent=intent,
        )
    status = (
        DocumentStatus.SUPERSEDED
        if intent == QueryIntent.HISTORICAL_TRUTH
        else DocumentStatus.ACTIVE
    )
    facts = registry.list_facts(
        system_name=system_name,
        version=version,
        status=status,
    )
    warnings: list[str] = []
    retrieval_sources: list[str] = []
    if facts:
        retrieval_sources.append("registry")
    vector_chunks, vector_warnings = _query_vector_chunks(
        query=query,
        registry=registry,
        settings=settings,
        system_name=system_name,
        version=version,
        status=status,
    )
    warnings.extend(vector_warnings)
    if vector_chunks:
        retrieval_sources.append("vector")
    keyword_chunks, keyword_warnings = _query_keyword_chunks(
        query=query,
        registry=registry,
        settings=settings,
        system_name=system_name,
        version=version,
        status=status,
    )
    warnings.extend(keyword_warnings)
    if keyword_chunks:
        retrieval_sources.append("keyword")
    graph_facts, graph_warning = _query_graph_facts(
        registry=registry,
        settings=settings,
        system_name=system_name,
        status=status,
    )
    if graph_warning:
        warnings.append(f"Neo4j graph facts unavailable: {graph_warning}")
    if graph_facts:
        retrieval_sources.append("graph")
    facts = _dedupe_facts(facts + graph_facts)
    chunks = _dedupe_chunks(_chunks_for_facts(registry, facts) + vector_chunks + keyword_chunks)
    if not facts and not chunks:
        return _unsupported(
            query=query,
            intent=intent,
            system_name=system_name,
            version=version,
            reason="No evidence found for the requested version/status.",
        )
    selected = _select_relevant_facts(query, facts)
    if selected:
        chunks = _dedupe_chunks(
            _chunks_for_facts(registry, selected) + vector_chunks + keyword_chunks
        )
        answer = _render_fact_answer(selected, status=status)
        return QueryResult(
            query=query,
            intent=intent.value,
            system_name=system_name,
            version=version,
            supported=True,
            answer=answer,
            facts=selected,
            chunks=chunks,
            evidence=_evidence_records(chunks),
            retrieval_sources=retrieval_sources,
            warnings=warnings,
        )
    return QueryResult(
        query=query,
        intent=intent.value,
        system_name=system_name,
        version=version,
        supported=True,
        answer=f"Found {len(chunks)} evidence chunk(s), but no extracted fact matched exactly.",
        chunks=chunks,
        evidence=_evidence_records(chunks),
        retrieval_sources=retrieval_sources,
        warnings=warnings
        + ["Answer limited to retrieved evidence chunks; no unsupported fact was generated."],
    )


def _answer_delta_query(
    *,
    query: str,
    system_name: str | None,
    settings: Settings,
    intent: QueryIntent,
) -> QueryResult:
    registry = SQLiteRegistry(settings.sqlite_db_path)
    deltas = registry.list_deltas(system_name=system_name)
    active_facts = registry.list_facts(system_name=system_name, status=DocumentStatus.ACTIVE)
    historical_facts = registry.list_facts(
        system_name=system_name,
        status=DocumentStatus.SUPERSEDED,
    )
    if not deltas:
        return _unsupported(
            query=query,
            intent=intent,
            system_name=system_name,
            version=None,
            reason="No delta records found. No impact claim can be made.",
        )
    selected = _select_relevant_deltas(query, deltas) or deltas
    chunks = _chunks_for_facts(
        registry,
        [
            fact
            for fact in active_facts + historical_facts
            if not selected
            or any(delta.fact_key is None or delta.fact_key == fact.fact_key for delta in selected)
        ],
    )
    answer = _render_delta_answer(selected)
    return QueryResult(
        query=query,
        intent=intent.value,
        system_name=system_name,
        supported=True,
        answer=answer,
        deltas=selected,
        chunks=chunks,
        evidence=_evidence_records(chunks),
        retrieval_sources=["registry"],
        warnings=[],
    )


def _answer_coverage_query(
    *,
    query: str,
    system_name: str | None,
    settings: Settings,
    intent: QueryIntent,
) -> QueryResult:
    registry = SQLiteRegistry(settings.sqlite_db_path)
    facts = registry.list_facts(system_name=system_name, status=DocumentStatus.ACTIVE)
    requirement_facts = [fact for fact in facts if fact.fact_type == "requirement"]
    if not requirement_facts:
        return _unsupported(
            query=query,
            intent=intent,
            system_name=system_name,
            version=None,
            reason="No active requirement evidence found. No coverage claim can be made.",
        )
    chunks = _chunks_for_facts(registry, requirement_facts)
    return QueryResult(
        query=query,
        intent=intent.value,
        system_name=system_name,
        supported=True,
        answer=f"Found {len(requirement_facts)} requirement evidence record(s) for coverage planning.",
        facts=requirement_facts,
        chunks=chunks,
        evidence=_evidence_records(chunks),
        retrieval_sources=["registry"],
    )


def _select_relevant_facts(query: str, facts: list[FactRecord]) -> list[FactRecord]:
    text = query.lower()
    selected = []
    for fact in facts:
        if fact.fact_key.lower().split(":", 1)[-1] in text:
            selected.append(fact)
        elif fact.fact_type in text:
            selected.append(fact)
        elif fact.value.lower() in text:
            selected.append(fact)
    return selected


def _select_relevant_deltas(query: str, deltas: list) -> list:
    text = query.lower()
    selected = []
    for delta in deltas:
        fact_key = (delta.fact_key or "").lower()
        if fact_key and fact_key.split(":", 1)[-1] in text:
            selected.append(delta)
        elif delta.old_value and delta.old_value.lower() in text:
            selected.append(delta)
        elif delta.new_value and delta.new_value.lower() in text:
            selected.append(delta)
    return selected


def _render_fact_answer(facts: list[FactRecord], *, status: DocumentStatus) -> str:
    parts = []
    seen: set[tuple[str, str, str | None, str, str]] = set()
    for fact in facts:
        claim_key = (fact.fact_key, fact.value, fact.unit, fact.version, status.value)
        if claim_key in seen:
            continue
        seen.add(claim_key)
        value = f"{fact.value} {fact.unit}".strip() if fact.unit else fact.value
        parts.append(f"{fact.fact_key} = {value} ({status.value}, version {fact.version})")
    return "; ".join(parts)


def _render_delta_answer(deltas: list) -> str:
    parts = []
    for delta in deltas:
        label = delta.fact_key or delta.affected_requirement_id or "fact"
        if delta.change_type == "modified":
            parts.append(f"{label} changed from {delta.old_value} to {delta.new_value}")
        elif delta.change_type == "added":
            parts.append(f"{label} added as {delta.new_value}")
        elif delta.change_type == "removed":
            parts.append(f"{label} removed from {delta.old_value}")
        else:
            parts.append(f"{label} {delta.change_type}")
    return "; ".join(parts)


def _chunks_for_facts(registry: SQLiteRegistry, facts: list[FactRecord]) -> list[ChunkRecord]:
    chunks_by_id: dict[str, ChunkRecord] = {}
    for fact in facts:
        chunks = registry.list_chunks(document_id=fact.document_id)
        for chunk in chunks:
            if chunk.chunk_id == fact.chunk_id:
                chunks_by_id[chunk.chunk_id] = chunk
    return list(chunks_by_id.values())


def _query_vector_chunks(
    *,
    query: str,
    registry: SQLiteRegistry,
    settings: Settings,
    system_name: str | None,
    version: str | None,
    status: DocumentStatus,
) -> tuple[list[ChunkRecord], list[str]]:
    filters = {
        "system_name": system_name,
        "version": version,
        "status": status.value,
    }
    try:
        selection = select_vector_store(settings)
        results = selection.store.query(
            query,
            filters=filters,
            top_k=5,
        )
    except Exception as exc:
        return [], [f"Vector chunk retrieval unavailable: {exc}"]
    chunk_ids = [result["chunk_id"] for result in results]
    if not chunk_ids:
        return [], []
    candidates = registry.list_chunks(
        system_name=system_name,
        version=version,
        status=status,
    )
    by_id = {chunk.chunk_id: chunk for chunk in candidates}
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id], []


def _query_keyword_chunks(
    *,
    query: str,
    registry: SQLiteRegistry,
    settings: Settings,
    system_name: str | None,
    version: str | None,
    status: DocumentStatus,
) -> tuple[list[ChunkRecord], list[str]]:
    if not settings.keyword_index_enabled:
        return [], []
    try:
        results = KeywordRetriever(registry).retrieve(
            query,
            system_name=system_name,
            version=version,
            status=status,
            top_k=5,
        )
    except Exception as exc:
        return [], [f"Keyword retrieval unavailable: {exc}"]
    chunk_ids = [result["chunk_id"] for result in results]
    if not chunk_ids:
        return [], []
    candidates = registry.list_chunks(
        system_name=system_name,
        version=version,
        status=status,
    )
    by_id = {chunk.chunk_id: chunk for chunk in candidates}
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id], []


def _query_graph_facts(
    *,
    registry: SQLiteRegistry,
    settings: Settings,
    system_name: str | None,
    status: DocumentStatus,
) -> tuple[list[FactRecord], str | None]:
    if not system_name:
        return [], None
    retriever = GraphRetriever(settings)
    result = (
        retriever.get_current_facts(system_name)
        if status == DocumentStatus.ACTIVE
        else retriever.get_historical_facts(system_name)
    )
    if result.warning:
        return [], result.warning
    chunks = {
        chunk.chunk_id: chunk
        for chunk in registry.list_chunks(system_name=system_name, status=status)
    }
    facts: list[FactRecord] = []
    for record in result.records:
        chunk = chunks.get(str(record.get("chunk_id")))
        if not chunk:
            continue
        fact_id = str(record.get("fact_id") or "")
        fact_key = str(record.get("fact_key") or "")
        value = str(record.get("value") or "")
        if not fact_id or not fact_key or not value:
            continue
        facts.append(
            FactRecord(
                fact_id=fact_id,
                fact_key=fact_key,
                fact_type=str(record.get("fact_type") or ""),
                value=value,
                unit=record.get("unit"),
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                system_name=chunk.system_name,
                version=chunk.version,
                status=status,
                evidence=chunk.text,
            )
        )
    return facts, None


def _dedupe_facts(facts: list[FactRecord]) -> list[FactRecord]:
    by_id: dict[str, FactRecord] = {}
    for fact in facts:
        by_id[fact.fact_id] = fact
    return list(by_id.values())


def _dedupe_chunks(chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    by_id: dict[str, ChunkRecord] = {}
    for chunk in chunks:
        by_id[chunk.chunk_id] = chunk
    return list(by_id.values())


def _evidence_records(chunks: list[ChunkRecord]) -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            system_name=chunk.system_name,
            version=chunk.version,
            source_name=chunk.source_name,
            page=chunk.page,
            text=chunk.text,
        )
        for chunk in chunks
    ]


def _unsupported(
    *,
    query: str,
    intent: QueryIntent,
    system_name: str | None,
    version: str | None,
    reason: str,
) -> QueryResult:
    return QueryResult(
        query=query,
        intent=intent.value,
        system_name=system_name,
        version=version,
        supported=False,
        answer=f"Unsupported: {reason}",
        warnings=[reason],
    )
