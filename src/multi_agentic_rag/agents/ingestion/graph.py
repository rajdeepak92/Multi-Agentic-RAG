"""Compiled LangGraph workflow for knowledge-base ingestion."""

from __future__ import annotations

from typing import Any, Literal

import structlog
from langgraph.graph import END, START, StateGraph
from structlog.contextvars import bind_contextvars, clear_contextvars

from multi_agentic_rag.agents.ingestion.schemas import IngestionRequest, IngestionResult
from multi_agentic_rag.agents.ingestion.state import IngestionState
from multi_agentic_rag.agents.knowledge_base import KnowledgeBaseStoringAgent
from multi_agentic_rag.agents.sub_agents import build_system_record
from multi_agentic_rag.common import IngestionStage
from multi_agentic_rag.config.logging import configure_logging
from multi_agentic_rag.domain import (
    DocumentStatus,
    IngestionRunRecord,
    IngestionRunStatus,
    IngestResult,
)
from multi_agentic_rag.exceptions import IngestionError
from multi_agentic_rag.utils.hashing import stable_id


class IngestionGraphRuntime:
    """Node implementation for the ingestion StateGraph."""

    def __init__(self, legacy_agent: KnowledgeBaseStoringAgent) -> None:
        self.legacy_agent = legacy_agent
        self.log = structlog.get_logger(__name__)

    async def validate_request(self, state: IngestionState) -> IngestionState:
        """Validate CLI scope, source path, version hint, and source hash."""

        try:
            request = IngestionRequest.model_validate(state["request"])
            settings = self.legacy_agent.settings_agent.load()
            configure_logging(settings.log_level)
            source = self.legacy_agent.resolver_agent.resolve(request.document_path)
            self.legacy_agent.versioning_agent.validate(source, request.version)
            source_hash = self.legacy_agent.hashing_agent.hash_source(source)
            return {
                **state,
                "request": request,
                "source_path": source,
                "requested_version": request.version,
                "source_hash": source_hash,
                "stage": IngestionStage.VALIDATED,
                "errors": [],
                "warnings": [],
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def check_dependencies(self, state: IngestionState) -> IngestionState:
        """Check mandatory PostgreSQL, Chroma, Neo4j, and lexical readiness."""

        try:
            settings = self.legacy_agent.settings_agent.load()
            runtime_paths = self.legacy_agent.runtime_agent.ensure(settings)
            bm25_ready, bm25_message = await self.legacy_agent.postgres_agent.check_bm25()
            if not bm25_ready:
                raise IngestionError(f"PostgreSQL BM25/FTS unavailable: {bm25_message}")
            chroma_ready, chroma_message = self.legacy_agent.chroma_agent.check()
            if not chroma_ready:
                raise IngestionError(f"Chroma unavailable: {chroma_message}")
            graph_ready, graph_message = self.legacy_agent.neo4j_agent.check()
            if not graph_ready:
                raise IngestionError(f"Neo4j required but unavailable: {graph_message}")
            return {
                **state,
                "runtime_paths": runtime_paths,
                "stage": IngestionStage.DEPENDENCIES_READY,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def resolve_lineage(self, state: IngestionState) -> IngestionState:
        """Resolve active version, coerce lineage, and create the ingestion run."""

        try:
            request = state["request"]
            previous_version = await self.legacy_agent.postgres_agent.active_version(
                system_name=request.system,
                kb_name=request.kb,
            )
            effective_version, version_warning = self.legacy_agent.versioning_agent.coerce(
                state["requested_version"],
                previous_version,
            )
            warnings = list(state.get("warnings", []))
            if version_warning:
                warnings.append(version_warning)
            old_chunks = []
            old_facts = []
            supersedes_version_id: str | None = None
            document_status = DocumentStatus.ACTIVE
            if previous_version:
                if self.legacy_agent.versioning_agent.is_newer(
                    effective_version,
                    previous_version.version,
                ):
                    supersedes_version_id = previous_version.document_version_id
                    old_chunks = await self.legacy_agent.postgres_agent.chunks_for_version(
                        previous_version.document_version_id
                    )
                    old_facts = await self.legacy_agent.postgres_agent.facts_for_version(
                        previous_version.document_version_id
                    )
                elif effective_version != previous_version.version:
                    document_status = DocumentStatus.SUPERSEDED
            run_id = stable_id(
                "ingestion_run",
                request.system,
                request.kb,
                effective_version,
                state["source_hash"],
            )
            bind_contextvars(ingestion_run_id=run_id, system=request.system, kb_name=request.kb)
            run_metadata = {
                "source": str(state["source_path"]),
                "content_hash": state["source_hash"],
            }
            if state["requested_version"] != effective_version:
                run_metadata["requested_version"] = state["requested_version"]
            await self.legacy_agent.postgres_agent.begin_run(
                IngestionRunRecord(
                    ingestion_run_id=run_id,
                    system_name=request.system,
                    kb_name=request.kb,
                    version=effective_version,
                    status=IngestionRunStatus.STARTED,
                    metadata=run_metadata,
                )
            )
            self.log.info("ingestion_started", source=str(state["source_path"]))
            return {
                **state,
                "run_id": run_id,
                "effective_version": effective_version,
                "previous_document_version": previous_version,
                "previous_document_id": previous_version.document_id if previous_version else None,
                "old_chunks": old_chunks,
                "old_facts": old_facts,
                "supersedes_version_id": supersedes_version_id,
                "document_status": document_status,
                "run_started": True,
                "warnings": warnings,
                "stage": IngestionStage.LINEAGE_RESOLVED,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def parse_document(self, state: IngestionState) -> IngestionState:
        """Copy the source document, parse pages, and create document records."""

        try:
            request = state["request"]
            settings = self.legacy_agent.settings_agent.load()
            managed_source = self.legacy_agent.source_storage_agent.store(
                state["source_path"],
                runtime_paths=state["runtime_paths"],
                system_name=request.system,
                kb_name=request.kb,
                version=state["effective_version"],
                content_hash=state["source_hash"],
            )
            pages = self.legacy_agent.parser_agent.parse(state["source_path"], settings)
            document_type = self.legacy_agent.metadata_agent.infer_type(
                state["source_path"],
                pages,
            )
            document, document_version = self.legacy_agent.metadata_agent.create_records(
                source=state["source_path"],
                managed_source=managed_source,
                system_name=request.system,
                kb_name=request.kb,
                version=state["effective_version"],
                content_hash=state["source_hash"],
                document_type=document_type,
                previous_version_id=state.get("supersedes_version_id"),
                status=state.get("document_status", DocumentStatus.ACTIVE),
            )
            return {
                **state,
                "managed_source": managed_source,
                "pages": pages,
                "document": document,
                "document_version": document_version,
                "document_id": document.document_id,
                "stage": IngestionStage.DOCUMENT_PARSED,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def chunk_document(self, state: IngestionState) -> IngestionState:
        """Chunk parsed pages and write the chunk manifest."""

        try:
            settings = self.legacy_agent.settings_agent.load()
            chunks = self.legacy_agent.chunking_agent.chunk(
                state["pages"],
                document_version=state["document_version"],
                settings=settings,
            )
            manifest_path = self.legacy_agent.manifest_agent.write(
                runtime_paths=state["runtime_paths"],
                document_version=state["document_version"],
                chunks=chunks,
            )
            return {
                **state,
                "chunks": chunks,
                "manifest_path": manifest_path,
                "stage": IngestionStage.DOCUMENT_CHUNKED,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def extract_knowledge(self, state: IngestionState) -> IngestionState:
        """Extract deterministic facts and optional LLM review metadata."""

        try:
            facts = self.legacy_agent.fact_agent.extract(state["chunks"])
            if self.legacy_agent.fact_enrichment_agent:
                facts = await self.legacy_agent.fact_enrichment_agent.enrich(
                    chunks=state["chunks"],
                    facts=facts,
                )
            return {
                **state,
                "facts": facts,
                "stage": IngestionStage.KNOWLEDGE_EXTRACTED,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def validate_extracted_knowledge(self, state: IngestionState) -> IngestionState:
        """Validate required chunk and fact outputs before persistence."""

        try:
            self.legacy_agent.validation_agent.validate(
                chunks=state["chunks"],
                facts=state["facts"],
            )
            return {**state, "stage": IngestionStage.KNOWLEDGE_VALIDATED}
        except Exception as exc:
            return _state_error(state, exc)

    async def compute_deltas(self, state: IngestionState) -> IngestionState:
        """Compute version deltas when a newer active version is ingested."""

        try:
            previous_version = state.get("previous_document_version")
            deltas = (
                self.legacy_agent.delta_agent.compute(
                    system_name=state["request"].system,
                    kb_name=state["request"].kb,
                    previous_version=previous_version,
                    document_version=state["document_version"],
                    old_facts=state.get("old_facts", []),
                    new_facts=state["facts"],
                )
                if previous_version and state.get("supersedes_version_id")
                else []
            )
            return {**state, "deltas": deltas, "stage": IngestionStage.DELTAS_COMPUTED}
        except Exception as exc:
            return _state_error(state, exc)

    async def persist_postgres(self, state: IngestionState) -> IngestionState:
        """Persist the authoritative ingestion bundle to PostgreSQL."""

        try:
            request = state["request"]
            await self.legacy_agent.postgres_agent.persist(
                system=build_system_record(request.system),
                document=state["document"],
                document_version=state["document_version"],
                chunks=state["chunks"],
                facts=state["facts"],
                deltas=state.get("deltas", []),
                superseded_version_id=state.get("supersedes_version_id"),
            )
            await _mark_ingestion_stage(
                self.legacy_agent.postgres_agent,
                state["run_id"],
                IngestionRunStatus.POSTGRES_COMMITTED,
            )
            return {
                **state,
                "postgres_status": "succeeded",
                "stage": IngestionStage.POSTGRES_COMMITTED,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def index_chroma(self, state: IngestionState) -> IngestionState:
        """Persist chunk embeddings and refresh superseded chunk metadata."""

        try:
            indexed_count = self.legacy_agent.chroma_agent.index(state["chunks"])
            if indexed_count != len(state["chunks"]):
                raise IngestionError(
                    f"Chroma indexed {indexed_count} chunks but ingestion produced "
                    f"{len(state['chunks'])}."
                )
            superseded_chunks = [
                chunk.model_copy(update={"status": DocumentStatus.SUPERSEDED})
                for chunk in state.get("old_chunks", [])
            ]
            refreshed_count = self.legacy_agent.chroma_agent.index(superseded_chunks)
            if refreshed_count != len(superseded_chunks):
                raise IngestionError(
                    f"Chroma refreshed {refreshed_count} superseded chunks but expected "
                    f"{len(superseded_chunks)}."
                )
            await _mark_ingestion_stage(
                self.legacy_agent.postgres_agent,
                state["run_id"],
                IngestionRunStatus.CHROMA_INDEXED,
            )
            chroma_status = f"indexed:{indexed_count}"
            if superseded_chunks:
                chroma_status = f"{chroma_status};superseded_refreshed:{refreshed_count}"
            return {
                **state,
                "chroma_status": chroma_status,
                "stage": IngestionStage.CHROMA_INDEXED,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def project_neo4j(self, state: IngestionState) -> IngestionState:
        """Project the synchronized graph representation into Neo4j."""

        try:
            self.legacy_agent.neo4j_agent.project(
                document=state["document"],
                document_version=state["document_version"],
                chunks=state["chunks"],
                facts=state["facts"],
                deltas=state.get("deltas", []),
            )
            await _mark_ingestion_stage(
                self.legacy_agent.postgres_agent,
                state["run_id"],
                IngestionRunStatus.NEO4J_PROJECTED,
            )
            return {
                **state,
                "neo4j_status": "projected",
                "stage": IngestionStage.NEO4J_PROJECTED,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def finalize_ingestion(self, state: IngestionState) -> IngestionState:
        """Re-check lexical readiness, mark completion, and build the typed result."""

        try:
            bm25_ready, bm25_message = await self.legacy_agent.postgres_agent.check_bm25()
            if not bm25_ready:
                raise IngestionError(f"PostgreSQL BM25/FTS unavailable: {bm25_message}")
            await self.legacy_agent.postgres_agent.succeed_run(
                state["run_id"],
                document_id=state["document"].document_id,
                document_version_id=state["document_version"].document_version_id,
            )
            ingest_result = IngestResult(
                document_id=state["document"].document_id,
                document_version_id=state["document_version"].document_version_id,
                chunks_count=len(state["chunks"]),
                facts_count=len(state["facts"]),
                deltas_count=len(state.get("deltas", [])),
                postgres_status=state["postgres_status"],
                chroma_status=state["chroma_status"],
                neo4j_status=state["neo4j_status"],
                bm25_status="ready",
                ingestion_run_id=state["run_id"],
                warnings=state.get("warnings", []),
            )
            self.log.info(
                "ingestion_succeeded",
                chunks=len(state["chunks"]),
                facts=len(state["facts"]),
                deltas=len(state.get("deltas", [])),
            )
            clear_contextvars()
            return {
                **state,
                "bm25_status": "ready",
                "ingest_result": ingest_result,
                "result": IngestionResult(
                    status="succeeded",
                    ingest_result=ingest_result,
                    run_id=state["run_id"],
                    warnings=state.get("warnings", []),
                ),
                "stage": IngestionStage.COMPLETED,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def fail_ingestion(self, state: IngestionState) -> IngestionState:
        """Mark the run failed when the graph reached a typed failure state."""

        errors = state.get("errors", [])
        if state.get("run_started") and state.get("run_id"):
            try:
                await self.legacy_agent.postgres_agent.fail_run(
                    state["run_id"],
                    "; ".join(errors) if errors else "Ingestion failed.",
                )
            except Exception as exc:  # pragma: no cover - secondary failure
                self.log.warning("failed_to_mark_ingestion_failed", error=str(exc))
        if errors:
            self.log.error("ingestion_failed", error="; ".join(errors))
        clear_contextvars()
        return {
            **state,
            "stage": IngestionStage.FAILED,
            "result": IngestionResult(
                status="failed",
                run_id=state.get("run_id"),
                errors=errors or ["Ingestion failed."],
                warnings=state.get("warnings", []),
            ),
        }


def build_ingestion_graph(legacy_agent: KnowledgeBaseStoringAgent) -> Any:
    """Build and compile the mandatory ingestion StateGraph."""

    runtime = IngestionGraphRuntime(legacy_agent)
    graph = StateGraph(IngestionState)
    graph.add_node("validate_request", runtime.validate_request)
    graph.add_node("check_dependencies", runtime.check_dependencies)
    graph.add_node("resolve_lineage", runtime.resolve_lineage)
    graph.add_node("parse_document", runtime.parse_document)
    graph.add_node("chunk_document", runtime.chunk_document)
    graph.add_node("extract_knowledge", runtime.extract_knowledge)
    graph.add_node("validate_extracted_knowledge", runtime.validate_extracted_knowledge)
    graph.add_node("compute_deltas", runtime.compute_deltas)
    graph.add_node("persist_postgres", runtime.persist_postgres)
    graph.add_node("index_chroma", runtime.index_chroma)
    graph.add_node("project_neo4j", runtime.project_neo4j)
    graph.add_node("finalize_ingestion", runtime.finalize_ingestion)
    graph.add_node("fail_ingestion", runtime.fail_ingestion)

    graph.add_edge(START, "validate_request")
    _guarded_edge(graph, "validate_request", "check_dependencies")
    _guarded_edge(graph, "check_dependencies", "resolve_lineage")
    _guarded_edge(graph, "resolve_lineage", "parse_document")
    _guarded_edge(graph, "parse_document", "chunk_document")
    _guarded_edge(graph, "chunk_document", "extract_knowledge")
    _guarded_edge(graph, "extract_knowledge", "validate_extracted_knowledge")
    _guarded_edge(graph, "validate_extracted_knowledge", "compute_deltas")
    _guarded_edge(graph, "compute_deltas", "persist_postgres")
    _guarded_edge(graph, "persist_postgres", "index_chroma")
    _guarded_edge(graph, "index_chroma", "project_neo4j")
    _guarded_edge(graph, "project_neo4j", "finalize_ingestion")
    graph.add_conditional_edges(
        "finalize_ingestion",
        _route_after_stage,
        {"continue": END, "fail": "fail_ingestion"},
    )
    graph.add_edge("fail_ingestion", END)
    return graph.compile()


def _guarded_edge(graph: Any, source: str, target: str) -> None:
    graph.add_conditional_edges(
        source,
        _route_after_stage,
        {"continue": target, "fail": "fail_ingestion"},
    )


def _route_after_stage(state: IngestionState) -> Literal["continue", "fail"]:
    return "fail" if state.get("errors") else "continue"


def _state_error(state: IngestionState, exc: Exception) -> IngestionState:
    errors = [*state.get("errors", []), str(exc)]
    return {
        **state,
        "errors": errors,
        "stage": IngestionStage.FAILED,
    }


async def _mark_ingestion_stage(
    postgres_agent: object,
    ingestion_run_id: str,
    status: IngestionRunStatus,
) -> None:
    mark_stage = getattr(postgres_agent, "mark_stage", None)
    if mark_stage is None:
        return
    await mark_stage(ingestion_run_id, status)
