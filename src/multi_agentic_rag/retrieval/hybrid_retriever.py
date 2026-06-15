"""Evidence-verified hybrid retrieval facade."""

from __future__ import annotations

import re

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.extraction.rule_extractors import extract_facts_from_text
from multi_agentic_rag.llm import AnswerDraft, select_llm_client
from multi_agentic_rag.models import ChunkRecord, DocumentStatus, EvidenceRecord, QueryResult
from multi_agentic_rag.models.graph import FactRecord
from multi_agentic_rag.retrieval.graph_retriever import GraphRetriever
from multi_agentic_rag.retrieval.intent import QueryIntent, detect_intent
from multi_agentic_rag.retrieval.keyword_retriever import KeywordRetriever
from multi_agentic_rag.retrieval.reranker import select_reranker
from multi_agentic_rag.storage.registry import Registry, select_registry
from multi_agentic_rag.storage.vector_factory import select_vector_store


def answer_query(
    query: str,
    *,
    system_name: str | None = None,
    version: str | None = None,
    settings: Settings | None = None,
) -> QueryResult:
    """Return a deterministic answer only when evidence exists."""

    intent = detect_intent(query)
    if not system_name:
        return _unsupported(
            query=query,
            intent=intent,
            system_name=system_name,
            version=version,
            reason="Document-scoped chat requires --system.",
        )
    if _is_framework_or_out_of_scope_query(query):
        return _unsupported(
            query=query,
            intent=intent,
            system_name=system_name,
            version=version,
            reason=(
                "Framework, setup, and out-of-scope questions are not answered by chat. "
                "Ask only about evidence in the selected system."
            ),
        )
    settings = settings or get_settings()
    registry = select_registry(settings).registry
    registry.initialize()
    retrieval_query = _expand_query_for_retrieval(query)

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
    status = _status_filter(intent=intent, version=version)
    document_scope = _infer_document_scope(
        registry=registry,
        query=query,
        system_name=system_name,
        version=version,
        status=status,
    )
    facts = registry.list_facts(
        system_name=system_name,
        version=version,
        status=status,
    )
    if document_scope:
        facts = [fact for fact in facts if fact.document_id in document_scope]
    registry_fact_ids = {fact.fact_id for fact in facts}
    warnings: list[str] = []
    retrieval_sources: list[str] = []
    vector_chunks, vector_warnings = _query_vector_chunks(
        query=retrieval_query,
        registry=registry,
        settings=settings,
        system_name=system_name,
        version=version,
        status=status,
        document_scope=document_scope,
    )
    warnings.extend(vector_warnings)
    if vector_chunks:
        retrieval_sources.append("vector")
    keyword_chunks, keyword_warnings = _query_keyword_chunks(
        query=retrieval_query,
        registry=registry,
        settings=settings,
        system_name=system_name,
        version=version,
        status=status,
        document_scope=document_scope,
    )
    warnings.extend(keyword_warnings)
    if keyword_chunks:
        retrieval_sources.append("keyword")
    graph_facts, graph_warning = _query_graph_facts(
        registry=registry,
        settings=settings,
        system_name=system_name,
        version=version,
        status=status,
        document_scope=document_scope,
    )
    if graph_warning:
        warnings.append(f"Neo4j graph facts unavailable: {graph_warning}")
    if graph_facts:
        retrieval_sources.append("graph")
    elif _target_graphrag_required(settings):
        return _unsupported(
            query=query,
            intent=intent,
            system_name=system_name,
            version=version,
            reason=(
                "Target GraphRAG mode requires Neo4j graph evidence for the requested "
                "system/version."
            ),
        )
    facts = _dedupe_facts(facts + graph_facts)
    retrieved_chunks = _dedupe_chunks(vector_chunks + keyword_chunks)
    if _is_scope_query(query):
        retrieved_chunks = _dedupe_chunks(
            retrieved_chunks + _scope_context_chunks(registry, retrieved_chunks)
        )
    retrieved_chunks, reranker_warning = _rerank_chunks(
        query=query,
        chunks=retrieved_chunks,
        settings=settings,
    )
    if reranker_warning:
        warnings.append(reranker_warning)
    elif retrieved_chunks and settings.reranker_provider != "none":
        retrieval_sources.append("reranker")
    if not facts and not retrieved_chunks:
        return _unsupported(
            query=query,
            intent=intent,
            system_name=system_name,
            version=version,
            reason="No evidence found for the requested version/status.",
        )
    selected = _select_relevant_facts(query, facts)
    if selected:
        selected_sources = list(retrieval_sources)
        if any(fact.fact_id in registry_fact_ids for fact in selected):
            selected_sources.insert(0, "registry")
        chunks = _dedupe_chunks(
            _chunks_for_facts(registry, selected) + retrieved_chunks
        )
        answer = _render_fact_answer(selected, status=status)
        answer, synthesis_warnings = _maybe_synthesize_answer(
            query=query,
            deterministic_answer=answer,
            chunks=chunks,
            settings=settings,
        )
        warnings.extend(synthesis_warnings)
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
            retrieval_sources=selected_sources,
            warnings=warnings,
        )
    answer, answer_chunks = _render_chunk_answer(query, retrieved_chunks)
    answer, synthesis_warnings = _maybe_synthesize_answer(
        query=query,
        deterministic_answer=answer,
        chunks=answer_chunks,
        settings=settings,
    )
    return QueryResult(
        query=query,
        intent=intent.value,
        system_name=system_name,
        version=version,
        supported=True,
        answer=answer,
        chunks=answer_chunks,
        evidence=_evidence_records(answer_chunks),
        retrieval_sources=[
            source for source in retrieval_sources if source in {"vector", "keyword"}
        ],
        warnings=warnings
        + synthesis_warnings
        + ["Answer is extractive from retrieved chunks; no exact extracted fact matched."],
    )


def _answer_delta_query(
    *,
    query: str,
    system_name: str | None,
    settings: Settings,
    intent: QueryIntent,
) -> QueryResult:
    registry = select_registry(settings).registry
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
    registry = select_registry(settings).registry
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
        answer=(
            f"Found {len(requirement_facts)} requirement evidence record(s) "
            "for coverage planning."
        ),
        facts=requirement_facts,
        chunks=chunks,
        evidence=_evidence_records(chunks),
        retrieval_sources=["registry"],
    )


def _status_filter(
    *,
    intent: QueryIntent,
    version: str | None,
) -> DocumentStatus | None:
    if intent == QueryIntent.HISTORICAL_TRUTH:
        return DocumentStatus.SUPERSEDED
    if version:
        return None
    return DocumentStatus.ACTIVE


def _infer_document_scope(
    *,
    registry: Registry,
    query: str,
    system_name: str | None,
    version: str | None,
    status: DocumentStatus | None,
) -> set[str] | None:
    query_text = _normalized_token_text(query)
    if not query_text:
        return None
    matches: set[str] = set()
    for document in registry.list_documents(system_name=system_name, status=status):
        if version and document.version != version:
            continue
        tokens = _source_tokens(document.source_name)
        if len(tokens) < 2:
            continue
        for start in range(len(tokens)):
            for end in range(start + 2, len(tokens) + 1):
                phrase_tokens = tokens[start:end]
                if not any(re.fullmatch(r"v\d+", token) for token in phrase_tokens):
                    continue
                if " ".join(phrase_tokens) in query_text:
                    matches.add(document.document_id)
                    break
            if document.document_id in matches:
                break
    return matches or None


def _normalized_token_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _source_tokens(source_name: str) -> list[str]:
    stem = source_name.rsplit(".", 1)[0]
    return re.findall(r"[a-z0-9]+", stem.lower())


QUERY_SENSORS = (
    "temperature",
    "pressure",
    "vibration",
    "humidity",
    "flow",
    "voltage",
    "current",
    "speed",
    "level",
)


def _is_scope_query(query: str) -> bool:
    text = query.lower()
    return any(
        phrase in text
        for phrase in (
            "covered",
            "covering",
            "what is covered",
            "what are covered",
            "in scope",
            "scope",
        )
    )


def _is_threshold_query(query: str) -> bool:
    text = query.lower()
    return any(
        phrase in text
        for phrase in (
            "threshold",
            "limit",
            "setpoint",
            "maximum",
            "minimum",
            "critical level",
        )
    )


def _is_framework_or_out_of_scope_query(query: str) -> bool:
    text = query.lower()
    blocked_phrases = (
        "how does this framework",
        "how does the framework",
        "what is this framework",
        "explain the framework",
        "setup",
        "install",
        "readme",
        "architecture",
        "langgraph",
        "postgresql",
        "weaviate",
        "openai",
        "docker",
    )
    return any(phrase in text for phrase in blocked_phrases)


def _expand_query_for_retrieval(query: str) -> str:
    expansions: list[str] = []
    if _is_scope_query(query):
        expansions.append(
            "scope in scope business scope objective objectives included includes "
            "supports system overview consists"
        )
    if _is_threshold_query(query):
        expansions.append("threshold max maximum critical level normal range min sensor data sheet")
    return " ".join([query, *expansions])


def _scope_context_chunks(
    registry: Registry,
    chunks: list[ChunkRecord],
) -> list[ChunkRecord]:
    additions: list[ChunkRecord] = []
    by_document: dict[str, list[ChunkRecord]] = {}
    for chunk in chunks:
        if not _contains_scope_start(chunk.text):
            continue
        document_chunks = by_document.setdefault(
            chunk.document_id,
            registry.list_chunks(document_id=chunk.document_id),
        )
        ordered = sorted(document_chunks, key=lambda item: (item.page, item.chunk_index))
        start_index = next(
            (index for index, item in enumerate(ordered) if item.chunk_id == chunk.chunk_id),
            None,
        )
        if start_index is None:
            continue
        for candidate in ordered[start_index + 1 : start_index + 4]:
            additions.append(candidate)
            if _contains_scope_end(candidate.text):
                break
    return additions


def _contains_scope_start(text: str) -> bool:
    return bool(re.search(r"\bin\s+scope\b", text, flags=re.IGNORECASE))


def _contains_scope_end(text: str) -> bool:
    return bool(re.search(r"\bout\s+of\s+scope\b", text, flags=re.IGNORECASE))


def _select_relevant_facts(query: str, facts: list[FactRecord]) -> list[FactRecord]:
    if _is_threshold_query(query):
        selected = _select_threshold_facts(query, facts)
        if selected:
            return selected
        return []
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


def _select_threshold_facts(query: str, facts: list[FactRecord]) -> list[FactRecord]:
    candidates = [fact for fact in facts if fact.fact_type == "threshold"]
    if not candidates:
        return []
    sensors = _query_sensors(query)
    if sensors:
        sensor_matches = [
            fact
            for fact in candidates
            if _threshold_sensor(fact) in sensors
            or any(sensor in fact.fact_key for sensor in sensors)
        ]
        if sensor_matches:
            candidates = sensor_matches
    kinds = _query_threshold_kinds(query)
    if kinds:
        kind_matches = [fact for fact in candidates if _threshold_kind(fact) in kinds]
        if kind_matches:
            candidates = kind_matches
    return sorted(candidates, key=lambda fact: _threshold_sort_key(fact, query))


def _query_sensors(query: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    return {sensor for sensor in QUERY_SENSORS if sensor in tokens}


def _query_threshold_kinds(query: str) -> tuple[str, ...]:
    text = query.lower()
    if any(term in text for term in ("critical", "above", ">")):
        return ("critical",)
    if any(term in text for term in ("maximum", "max", "upper")):
        return ("max", "critical")
    if any(term in text for term in ("minimum", "min", "lower")):
        return ("min",)
    if "normal" in text:
        return ("normal_range",)
    return ()


def _threshold_sensor(fact) -> str:
    sensor = fact.metadata.get("sensor") if getattr(fact, "metadata", None) else None
    if sensor:
        return str(sensor).lower()
    parts = fact.fact_key.split(":")
    return parts[1].lower() if len(parts) > 1 else ""


def _threshold_kind(fact) -> str:
    kind = fact.metadata.get("threshold_kind") if getattr(fact, "metadata", None) else None
    if kind:
        return str(kind).lower()
    parts = fact.fact_key.split(":")
    return parts[2].lower() if len(parts) > 2 else ""


def _threshold_sort_key(fact, query: str) -> tuple[int, int, str]:
    kinds = _query_threshold_kinds(query)
    kind = _threshold_kind(fact)
    kind_rank = kinds.index(kind) if kind in kinds else len(kinds)
    return (kind_rank, 0 if _threshold_sensor(fact) in _query_sensors(query) else 1, fact.fact_key)


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


def _render_fact_answer(
    facts: list[FactRecord],
    *,
    status: DocumentStatus | None,
) -> str:
    parts = []
    seen: set[tuple[str, str, str | None, str, str]] = set()
    for fact in facts:
        status_value = status.value if status else fact.status.value
        claim_key = (fact.fact_key, fact.value, fact.unit, fact.version, status_value)
        if claim_key in seen:
            continue
        seen.add(claim_key)
        value = f"{fact.value} {fact.unit}".strip() if fact.unit else fact.value
        label = _fact_label(fact)
        parts.append(f"{label} = {value} ({status_value}, version {fact.version})")
    return "; ".join(parts)


def _fact_label(fact) -> str:
    if fact.fact_type == "threshold":
        sensor = _threshold_sensor(fact) or "value"
        kind = _threshold_kind(fact)
        labels = {
            "normal_range": f"{sensor} normal range",
            "min": f"{sensor} min threshold",
            "max": f"{sensor} max threshold",
            "critical": f"{sensor} critical level",
        }
        return labels.get(kind, f"{sensor} threshold")
    return fact.fact_key


def _render_chunk_answer(
    query: str,
    chunks: list[ChunkRecord],
) -> tuple[str, list[ChunkRecord]]:
    if _is_threshold_query(query):
        threshold_items = _extract_threshold_items(query, chunks)
        if threshold_items:
            lines = ["Based on retrieved evidence, the threshold values are:"]
            lines.extend(
                f"- {_fact_label(fact)} = {_fact_value(fact)} ({chunk.source_name} p.{chunk.page})"
                for fact, chunk in threshold_items[:8]
            )
            return "\n".join(lines), _chunks_for_fact_items(threshold_items)
    if _is_scope_query(query):
        scope_items = _extract_scope_items(chunks)
        if scope_items:
            lines = ["Based on retrieved evidence, the covered scope is:"]
            lines.extend(
                f"- {item} ({chunk.source_name} p.{chunk.page})"
                for item, chunk in scope_items[:12]
            )
            return "\n".join(lines), _chunks_for_text_items(scope_items)
    excerpts = _extract_relevant_excerpts(query, chunks)
    if excerpts:
        lines = ["Retrieved evidence excerpts:"]
        lines.extend(
            f"- {excerpt} ({chunk.source_name} p.{chunk.page})"
            for excerpt, chunk in excerpts[:5]
        )
        return "\n".join(lines), _chunks_for_text_items(excerpts)
    return f"Found {len(chunks)} evidence chunk(s), but no exact extracted fact matched.", chunks


def _extract_threshold_items(
    query: str,
    chunks: list[ChunkRecord],
) -> list[tuple[object, ChunkRecord]]:
    items: list[tuple[object, ChunkRecord]] = []
    for chunk in chunks:
        selected = _select_threshold_facts(query, list(extract_facts_from_text(chunk.text)))
        items.extend((fact, chunk) for fact in selected)
    return _dedupe_fact_items(items)


def _fact_value(fact) -> str:
    return f"{fact.value} {fact.unit}".strip() if fact.unit else fact.value


def _extract_scope_items(chunks: list[ChunkRecord]) -> list[tuple[str, ChunkRecord]]:
    items: list[tuple[str, ChunkRecord]] = []
    in_scope = False
    for chunk in sorted(chunks, key=lambda item: (item.source_name, item.page, item.chunk_index)):
        for line in chunk.text.splitlines():
            clean = _clean_evidence_line(line)
            if not clean:
                continue
            if _contains_scope_end(clean):
                in_scope = False
                break
            if _contains_scope_start(clean):
                in_scope = True
                continue
            if in_scope and _looks_like_evidence_item(clean):
                items.append((clean, chunk))
    if items:
        return _dedupe_text_items(items)

    # Some parsers split "3.1 In Scope" into the previous chunk. If only the
    # continuation chunk was retrieved, treat text before "Out of Scope" as scope evidence.
    for chunk in sorted(chunks, key=lambda item: (item.source_name, item.page, item.chunk_index)):
        if not _contains_scope_end(chunk.text):
            continue
        for line in chunk.text.splitlines():
            clean = _clean_evidence_line(line)
            if not clean or _contains_scope_end(clean):
                break
            if _looks_like_evidence_item(clean):
                items.append((clean, chunk))
    return _dedupe_text_items(items)


def _extract_relevant_excerpts(
    query: str,
    chunks: list[ChunkRecord],
) -> list[tuple[str, ChunkRecord]]:
    query_terms = {
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2 and token not in {"what", "are", "the", "tell", "about"}
    }
    scored: list[tuple[int, str, ChunkRecord]] = []
    for chunk in chunks:
        for line in chunk.text.splitlines():
            clean = _clean_evidence_line(line)
            if not clean or not _looks_like_evidence_item(clean):
                continue
            line_terms = set(re.findall(r"[a-z0-9]+", clean.lower()))
            score = len(query_terms & line_terms)
            if score:
                scored.append((score, clean, chunk))
    scored.sort(key=lambda item: (-item[0], item[2].page, item[2].chunk_index))
    return _dedupe_text_items([(line, chunk) for _, line, chunk in scored])


def _clean_evidence_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" -\t")


def _looks_like_evidence_item(line: str) -> bool:
    if len(line) < 8:
        return False
    lower = line.lower()
    if lower.endswith(".markdown") or re.fullmatch(r"\d{4}-\d{2}-\d{2}", lower):
        return False
    if re.fullmatch(r"\d+\s*/\s*\d+", lower):
        return False
    if re.fullmatch(r"\d+(?:\.\d+)*\.?\s+[a-z ]+", lower):
        return False
    return True


def _dedupe_text_items(items: list[tuple[str, ChunkRecord]]) -> list[tuple[str, ChunkRecord]]:
    deduped: list[tuple[str, ChunkRecord]] = []
    seen: set[str] = set()
    for text, chunk in items:
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((text, chunk))
    return deduped


def _chunks_for_text_items(items: list[tuple[str, ChunkRecord]]) -> list[ChunkRecord]:
    return _dedupe_chunks([chunk for _, chunk in items])


def _dedupe_fact_items(items: list[tuple[object, ChunkRecord]]) -> list[tuple[object, ChunkRecord]]:
    deduped: list[tuple[object, ChunkRecord]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for fact, chunk in items:
        key = (fact.fact_key, fact.value, fact.unit)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((fact, chunk))
    return deduped


def _chunks_for_fact_items(items: list[tuple[object, ChunkRecord]]) -> list[ChunkRecord]:
    return _dedupe_chunks([chunk for _, chunk in items])


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


def _chunks_for_facts(registry: Registry, facts: list[FactRecord]) -> list[ChunkRecord]:
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
    registry: Registry,
    settings: Settings,
    system_name: str | None,
    version: str | None,
    status: DocumentStatus | None,
    document_scope: set[str] | None,
) -> tuple[list[ChunkRecord], list[str]]:
    filters = {
        "system_name": system_name,
        "version": version,
        "status": status.value if status else None,
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
    if document_scope:
        candidates = [chunk for chunk in candidates if chunk.document_id in document_scope]
    by_id = {chunk.chunk_id: chunk for chunk in candidates}
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id], []


def _query_keyword_chunks(
    *,
    query: str,
    registry: Registry,
    settings: Settings,
    system_name: str | None,
    version: str | None,
    status: DocumentStatus | None,
    document_scope: set[str] | None,
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
    if document_scope:
        candidates = [chunk for chunk in candidates if chunk.document_id in document_scope]
    by_id = {chunk.chunk_id: chunk for chunk in candidates}
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id], []


def _query_graph_facts(
    *,
    registry: Registry,
    settings: Settings,
    system_name: str | None,
    version: str | None,
    status: DocumentStatus | None,
    document_scope: set[str] | None,
) -> tuple[list[FactRecord], str | None]:
    if not system_name:
        return [], None
    retriever = GraphRetriever(settings)
    if version:
        result = retriever.get_facts_by_version(system_name, version)
    elif status == DocumentStatus.ACTIVE:
        result = retriever.get_current_facts(system_name)
    elif status == DocumentStatus.SUPERSEDED:
        result = retriever.get_historical_facts(system_name)
    else:
        return [], None
    if result.warning:
        return [], result.warning
    chunks = {
        chunk.chunk_id: chunk
        for chunk in registry.list_chunks(system_name=system_name, version=version, status=status)
        if not document_scope or chunk.document_id in document_scope
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
                status=status or chunk.status,
                evidence=chunk.text,
                semantic_key=record.get("semantic_key"),
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


def _rerank_chunks(
    *,
    query: str,
    chunks: list[ChunkRecord],
    settings: Settings,
) -> tuple[list[ChunkRecord], str | None]:
    if not chunks or settings.reranker_provider == "none":
        return chunks, None
    try:
        selection = select_reranker(settings)
        candidates = [
            {
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "chunk": chunk,
            }
            for chunk in chunks
        ]
        ranked = selection.reranker.rerank(query, candidates)
    except Exception as exc:
        return chunks, f"Reranking unavailable: {exc}"
    reranked_chunks = [item["chunk"] for item in ranked if item.get("chunk")]
    return reranked_chunks or chunks, None


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


def _maybe_synthesize_answer(
    *,
    query: str,
    deterministic_answer: str,
    chunks: list[ChunkRecord],
    settings: Settings,
) -> tuple[str, list[str]]:
    if settings.llm_provider == "none" or not chunks:
        return deterministic_answer, []
    client = select_llm_client(settings)
    ready, message = client.check_ready()
    if not ready:
        return deterministic_answer, [f"LLM answer synthesis disabled: {message}"]
    evidence_by_id = {
        chunk.chunk_id: {
            "source": chunk.source_name,
            "page": chunk.page,
            "version": chunk.version,
            "text": chunk.text[:1200],
        }
        for chunk in chunks[:8]
    }
    instructions = (
        "Rewrite the deterministic MARAG answer only using the provided evidence. "
        "Do not add facts, recommendations, or assumptions. "
        "Return used_evidence_ids that are present in the provided evidence map."
    )
    user_input = str(
        {
            "question": query,
            "deterministic_answer": deterministic_answer,
            "evidence": evidence_by_id,
        }
    )
    try:
        draft = client.parse(
            instructions=instructions,
            user_input=user_input,
            schema=AnswerDraft,
        )
    except Exception as exc:
        return deterministic_answer, [f"LLM answer synthesis fallback used: {exc}"]
    used_ids = set(draft.used_evidence_ids)
    if not draft.answer.strip() or not used_ids or not used_ids <= set(evidence_by_id):
        return deterministic_answer, ["LLM answer synthesis rejected: missing valid evidence ids."]
    return draft.answer.strip(), [f"LLM answer synthesis used via {client.provider}."]


def _target_graphrag_required(settings: Settings) -> bool:
    return settings.marag_target_mode == "target-graphrag" or settings.graphrag_required


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
