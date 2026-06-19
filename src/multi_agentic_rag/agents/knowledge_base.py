"""Knowledge-base ingestion orchestration."""

from __future__ import annotations

from pathlib import Path

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from multi_agentic_rag.agents.sub_agents import (
    ChromaIndexingAgent,
    ChunkingAgent,
    DeltaAnalysisAgent,
    DocumentResolutionAgent,
    DocumentVersioningAgent,
    FactExtractionAgent,
    HashingAgent,
    ManifestAgent,
    MetadataAgent,
    Neo4jGraphAgent,
    ParserAgent,
    PostgresPersistenceAgent,
    RuntimeDirectoryAgent,
    SettingsBootstrapAgent,
    SourceStorageAgent,
    ValidationAgent,
    build_system_record,
)
from multi_agentic_rag.config import Settings
from multi_agentic_rag.config.logging import configure_logging
from multi_agentic_rag.domain import (
    DocumentInput,
    DocumentStatus,
    IngestionRunRecord,
    IngestResult,
)
from multi_agentic_rag.domain.models import IngestionRunStatus
from multi_agentic_rag.exceptions import IngestionError
from multi_agentic_rag.infrastructure.chroma import ChromaVectorRepository
from multi_agentic_rag.infrastructure.neo4j import Neo4jGraphRepository
from multi_agentic_rag.infrastructure.postgres import PostgresKnowledgeRepository
from multi_agentic_rag.utils.hashing import stable_id


class KnowledgeBaseStoringAgent:
    """Top-level orchestrator for GraphRAG knowledge-base ingestion.

    The agent owns the canonical ingestion sequence: resolve, validate, hash, copy source,
    parse, chunk, manifest, extract facts, compute deltas, persist to PostgreSQL, index in
    Chroma, project to Neo4j, and mark the ingestion run. Every external boundary is
    injectable so tests can run with fakes and production can swap infrastructure adapters.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        settings_agent: SettingsBootstrapAgent | None = None,
        runtime_agent: RuntimeDirectoryAgent | None = None,
        resolver_agent: DocumentResolutionAgent | None = None,
        versioning_agent: DocumentVersioningAgent | None = None,
        hashing_agent: HashingAgent | None = None,
        source_storage_agent: SourceStorageAgent | None = None,
        metadata_agent: MetadataAgent | None = None,
        parser_agent: ParserAgent | None = None,
        chunking_agent: ChunkingAgent | None = None,
        manifest_agent: ManifestAgent | None = None,
        fact_agent: FactExtractionAgent | None = None,
        delta_agent: DeltaAnalysisAgent | None = None,
        postgres_agent: PostgresPersistenceAgent | None = None,
        chroma_agent: ChromaIndexingAgent | None = None,
        neo4j_agent: Neo4jGraphAgent | None = None,
        validation_agent: ValidationAgent | None = None,
    ) -> None:
        """Create a knowledge-base ingestion agent.

        Args:
            settings: Optional already-loaded runtime settings. When omitted, settings are
                loaded from environment and `.env` through `SettingsBootstrapAgent`.
            settings_agent: Optional settings loader override.
            runtime_agent: Optional runtime-directory manager override.
            resolver_agent: Optional document path resolver override.
            versioning_agent: Optional version validation/comparison override.
            hashing_agent: Optional source hashing override.
            source_storage_agent: Optional managed-source copy override.
            metadata_agent: Optional document metadata/record builder override.
            parser_agent: Optional source parser override.
            chunking_agent: Optional chunk creation override.
            manifest_agent: Optional chunk manifest writer override.
            fact_agent: Optional deterministic fact extractor override.
            delta_agent: Optional version delta analyzer override.
            postgres_agent: Optional PostgreSQL persistence boundary override.
            chroma_agent: Optional Chroma indexing boundary override.
            neo4j_agent: Optional Neo4j graph projection boundary override.
            validation_agent: Optional final ingestion validation override.
        """

        self.settings_agent = settings_agent or SettingsBootstrapAgent(settings)
        self.runtime_agent = runtime_agent or RuntimeDirectoryAgent()
        self.resolver_agent = resolver_agent or DocumentResolutionAgent()
        self.versioning_agent = versioning_agent or DocumentVersioningAgent()
        self.hashing_agent = hashing_agent or HashingAgent()
        self.source_storage_agent = source_storage_agent or SourceStorageAgent()
        self.metadata_agent = metadata_agent or MetadataAgent()
        self.parser_agent = parser_agent or ParserAgent()
        self.chunking_agent = chunking_agent or ChunkingAgent()
        self.manifest_agent = manifest_agent or ManifestAgent()
        self.fact_agent = fact_agent or FactExtractionAgent()
        self.delta_agent = delta_agent or DeltaAnalysisAgent()
        loaded_settings = self.settings_agent.load()
        self.postgres_agent = postgres_agent or PostgresPersistenceAgent(
            PostgresKnowledgeRepository.from_settings(loaded_settings)
        )
        self.chroma_agent = chroma_agent or ChromaIndexingAgent(
            ChromaVectorRepository.from_settings(loaded_settings)
        )
        self.neo4j_agent = neo4j_agent or Neo4jGraphAgent(Neo4jGraphRepository(loaded_settings))
        self.validation_agent = validation_agent or ValidationAgent()

    async def ingest(
        self,
        document_input: str | Path | DocumentInput,
        previous_knowledge_base: str | None = None,
        *,
        system: str,
        version: str,
    ) -> IngestResult:
        """Ingest one versioned source document into PostgreSQL, Chroma, and Neo4j.

        Args:
            document_input: Source path or `DocumentInput`. A `DocumentInput` can carry a
                knowledge-base name and optional caller metadata; plain paths use `default`.
            previous_knowledge_base: Backward-compatible name/context override for `--kb`.
                When provided, it becomes the target knowledge-base name.
            system: Stable system name that owns the document lineage.
            version: Version label for this ingest, such as `v1` or `v2`.

        Returns:
            IngestResult with document/version IDs, output counts, service statuses, and
            the ingestion run ID.

        Raises:
            IngestionError: If parsing, validation, persistence, graph projection, or required
            readiness checks fail.
        """

        settings = self.settings_agent.load()
        configure_logging(settings.log_level)
        source_value, kb_name = _normalize_document_input(document_input)
        if previous_knowledge_base:
            kb_name = previous_knowledge_base

        source = self.resolver_agent.resolve(source_value)
        requested_version = version
        self.versioning_agent.validate(source, requested_version)
        content_hash = self.hashing_agent.hash_source(source)
        ingestion_run_id = ""
        logger = structlog.get_logger(__name__)
        run_started = False
        try:
            runtime_paths = self.runtime_agent.ensure(settings)
            bm25_ready, bm25_message = await self.postgres_agent.check_bm25()
            if not bm25_ready:
                raise IngestionError(f"PostgreSQL BM25/FTS unavailable: {bm25_message}")
            chroma_ready, chroma_message = self.chroma_agent.check()
            if not chroma_ready:
                raise IngestionError(f"Chroma unavailable: {chroma_message}")
            graph_ready, graph_message = self.neo4j_agent.check()
            if not graph_ready:
                if settings.graphrag_required:
                    raise IngestionError(f"Neo4j required but unavailable: {graph_message}")
                raise IngestionError(
                    "Neo4j is mandatory for GraphRAG ingestion. "
                    f"Set GRAPHRAG_REQUIRED=true and fix Neo4j readiness: {graph_message}"
                )
            previous_version = await self.postgres_agent.active_version(
                system_name=system,
                kb_name=kb_name,
            )
            version, version_warning = self.versioning_agent.coerce(
                requested_version,
                previous_version,
            )
            warnings = [version_warning] if version_warning else []
            ingestion_run_id = stable_id("ingestion_run", system, kb_name, version, content_hash)
            bind_contextvars(ingestion_run_id=ingestion_run_id, system=system, kb_name=kb_name)
            run_metadata = {"source": str(source), "content_hash": content_hash}
            if requested_version != version:
                run_metadata["requested_version"] = requested_version
            run = IngestionRunRecord(
                ingestion_run_id=ingestion_run_id,
                system_name=system,
                kb_name=kb_name,
                version=version,
                status=IngestionRunStatus.STARTED,
                metadata=run_metadata,
            )
            await self.postgres_agent.begin_run(run)
            run_started = True
            logger.info("ingestion_started", source=str(source), version=version)

            managed_source = self.source_storage_agent.store(
                source,
                runtime_paths=runtime_paths,
                system_name=system,
                kb_name=kb_name,
                version=version,
                content_hash=content_hash,
            )
            pages = self.parser_agent.parse(source, settings)
            supersedes_version_id: str | None = None
            status = DocumentStatus.ACTIVE
            old_chunks = []
            old_facts = []
            if previous_version:
                if self.versioning_agent.is_newer(version, previous_version.version):
                    supersedes_version_id = previous_version.document_version_id
                    old_chunks = await self.postgres_agent.chunks_for_version(
                        previous_version.document_version_id
                    )
                    old_facts = await self.postgres_agent.facts_for_version(
                        previous_version.document_version_id
                    )
                elif version != previous_version.version:
                    status = DocumentStatus.SUPERSEDED
            document_type = self.metadata_agent.infer_type(source, pages)
            document, document_version = self.metadata_agent.create_records(
                source=source,
                managed_source=managed_source,
                system_name=system,
                kb_name=kb_name,
                version=version,
                content_hash=content_hash,
                document_type=document_type,
                previous_version_id=supersedes_version_id,
                status=status,
            )
            chunks = self.chunking_agent.chunk(
                pages,
                document_version=document_version,
                settings=settings,
            )
            manifest_path = self.manifest_agent.write(
                runtime_paths=runtime_paths,
                document_version=document_version,
                chunks=chunks,
            )
            facts = self.fact_agent.extract(chunks)
            deltas = (
                self.delta_agent.compute(
                    system_name=system,
                    kb_name=kb_name,
                    previous_version=previous_version,
                    document_version=document_version,
                    old_facts=old_facts,
                    new_facts=facts,
                )
                if previous_version and supersedes_version_id
                else []
            )
            self.validation_agent.validate(chunks=chunks, facts=facts)
            await self.postgres_agent.persist(
                system=build_system_record(system),
                document=document,
                document_version=document_version,
                chunks=chunks,
                facts=facts,
                deltas=deltas,
                superseded_version_id=supersedes_version_id,
            )
            postgres_status = "succeeded"

            indexed_count = self.chroma_agent.index(chunks)
            if indexed_count != len(chunks):
                raise IngestionError(
                    f"Chroma indexed {indexed_count} chunks but ingestion produced {len(chunks)}."
                )
            superseded_chunks = [
                chunk.model_copy(update={"status": DocumentStatus.SUPERSEDED})
                for chunk in old_chunks
            ]
            refreshed_superseded_count = self.chroma_agent.index(superseded_chunks)
            if refreshed_superseded_count != len(superseded_chunks):
                raise IngestionError(
                    "Chroma refreshed "
                    f"{refreshed_superseded_count} superseded chunks but expected "
                    f"{len(superseded_chunks)}."
                )
            chroma_status = f"indexed:{indexed_count}"
            if superseded_chunks:
                chroma_status = (
                    f"{chroma_status};superseded_refreshed:{refreshed_superseded_count}"
                )

            self.neo4j_agent.project(
                document=document,
                document_version=document_version,
                chunks=chunks,
                facts=facts,
                deltas=deltas,
            )
            neo4j_status = "projected"

            bm25_ready, bm25_message = await self.postgres_agent.check_bm25()
            if not bm25_ready:
                raise IngestionError(f"PostgreSQL BM25/FTS unavailable: {bm25_message}")
            bm25_status = "ready"
            await self.postgres_agent.succeed_run(
                ingestion_run_id,
                document_id=document.document_id,
                document_version_id=document_version.document_version_id,
            )
            logger.info(
                "ingestion_succeeded",
                chunks=len(chunks),
                facts=len(facts),
                deltas=len(deltas),
                manifest=str(manifest_path),
            )
            return IngestResult(
                document_id=document.document_id,
                document_version_id=document_version.document_version_id,
                chunks_count=len(chunks),
                facts_count=len(facts),
                deltas_count=len(deltas),
                postgres_status=postgres_status,
                chroma_status=chroma_status,
                neo4j_status=neo4j_status,
                bm25_status=bm25_status,
                ingestion_run_id=ingestion_run_id,
                warnings=warnings,
            )
        except Exception as exc:
            if run_started:
                try:
                    await self.postgres_agent.fail_run(ingestion_run_id, str(exc))
                except Exception as failure_exc:  # pragma: no cover - secondary failure
                    logger.warning("failed_to_mark_ingestion_failed", error=str(failure_exc))
            logger.error("ingestion_failed", error=str(exc))
            if isinstance(exc, IngestionError):
                raise
            raise IngestionError(str(exc)) from exc
        finally:
            clear_contextvars()


def _normalize_document_input(document_input: str | Path | DocumentInput) -> tuple[str | Path, str]:
    if isinstance(document_input, DocumentInput):
        return document_input.path, document_input.kb_name
    return document_input, "default"
