# mypy: ignore-errors
"""Async PostgreSQL repository."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import Select, bindparam, delete, func, literal_column, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import (
    ArtifactRecord,
    CanonicalFactRecord,
    ChunkRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    DocumentVersionRecord,
    EntityRecord,
    FactRecord,
    IngestionRunRecord,
    IngestionRunStatus,
    RequirementRecord,
    RetrievalResult,
    SystemRecord,
    WorkflowRunRecord,
    WorkflowStatus,
    WorkflowStepRecord,
)
from multi_agentic_rag.exceptions import ConfigError
from multi_agentic_rag.infrastructure.postgres.models import (
    ArtifactRecordModel,
    CanonicalFactModel,
    ChunkModel,
    DeltaModel,
    DocumentModel,
    DocumentVersionModel,
    EntityModel,
    FactModel,
    IngestionRunModel,
    RequirementModel,
    RetrievalMetadataModel,
    SystemModel,
    WorkflowRunModel,
    WorkflowStepModel,
)
from multi_agentic_rag.infrastructure.postgres.session import create_async_session_factory
from multi_agentic_rag.utils.hashing import stable_id

BM25Backend = Literal["pg_textsearch", "postgres_fts"]


@dataclass(frozen=True)
class PostgresLexicalReadiness:
    """Detailed readiness state for the configured PostgreSQL lexical backend."""

    connected: bool
    backend: str
    detail: str
    pg_textsearch_extension: bool | None = None
    bm25_index: bool | None = None
    bm25_operator: bool | None = None
    native_fts_index: bool | None = None

    @property
    def ready(self) -> bool:
        if not self.connected:
            return False
        if self.backend == "pg_textsearch":
            return (
                self.pg_textsearch_extension is True
                and self.bm25_index is True
                and self.bm25_operator is True
            )
        if self.backend == "postgres_fts":
            return self.native_fts_index is True
        return False


class PostgresKnowledgeRepository:
    """Authoritative async PostgreSQL repository."""

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        bm25_backend: BM25Backend = "pg_textsearch",
    ) -> None:
        """Initialize the repository with an async session factory.

        Args:
            session_factory: Callable that opens an ``AsyncSession`` or
                transaction-scoped async session context.
            bm25_backend: Lexical search backend. ``pg_textsearch`` uses the
                BM25 extension and ``postgres_fts`` uses native PostgreSQL FTS.
        """

        self.session_factory = session_factory
        self.bm25_backend = bm25_backend

    @classmethod
    def from_settings(cls, settings: Settings) -> PostgresKnowledgeRepository:
        """Build from configured DSN.

        Args:
            settings: Runtime configuration containing ``POSTGRES_DSN``.

        Returns:
            Repository using an async SQLAlchemy session factory.

        Raises:
            ConfigError: If PostgreSQL is required but no DSN is configured.
        """

        if not settings.postgres_dsn:
            raise ConfigError("POSTGRES_DSN is required.")
        return cls(
            create_async_session_factory(
                settings.postgres_dsn,
                connect_timeout=settings.postgres_connect_timeout_seconds,
                command_timeout=settings.postgres_command_timeout_seconds,
                statement_timeout_ms=settings.postgres_statement_timeout_ms,
                pool_size=settings.postgres_pool_size,
                max_overflow=settings.postgres_max_overflow,
                pool_recycle=settings.postgres_pool_recycle_seconds,
                pool_pre_ping=settings.postgres_pool_pre_ping,
            ),
            bm25_backend=settings.bm25_backend,
        )

    async def check_connection(self) -> tuple[bool, str]:
        """Verify PostgreSQL connectivity and configured lexical index availability."""

        readiness = await self.check_lexical_readiness()
        return readiness.ready, readiness.detail

    async def check_lexical_readiness(self) -> PostgresLexicalReadiness:
        """Return detailed PostgreSQL lexical readiness for doctor output."""

        try:
            async with self.session_factory() as session:
                await session.execute(text("SELECT 1"))
                if self.bm25_backend == "pg_textsearch":
                    extension = await session.execute(
                        text(
                            "SELECT EXISTS ("
                            "SELECT 1 FROM pg_extension WHERE extname = 'pg_textsearch'"
                            ")"
                        )
                    )
                    if not extension.scalar_one_or_none():
                        return PostgresLexicalReadiness(
                            connected=True,
                            backend=self.bm25_backend,
                            pg_textsearch_extension=False,
                            bm25_index=None,
                            detail=(
                                "pg_textsearch extension is not available in this "
                                "POSTGRES_DSN target."
                            ),
                        )
                    index = await session.execute(
                        text("SELECT to_regclass('idx_chunks_text_bm25')")
                    )
                    if index.scalar_one_or_none() is None:
                        return PostgresLexicalReadiness(
                            connected=True,
                            backend=self.bm25_backend,
                            pg_textsearch_extension=True,
                            bm25_index=False,
                            bm25_operator=None,
                            detail=(
                                "pg_textsearch BM25 index idx_chunks_text_bm25 is not "
                                "available; run `uv run --no-sync alembic upgrade head` "
                                "against this POSTGRES_DSN."
                            ),
                        )
                    try:
                        await session.execute(
                            text(
                                "SELECT chunk_id, "
                                "text <@> to_bm25query("
                                "'requirements user story', 'idx_chunks_text_bm25'"
                                ") AS score "
                                "FROM chunks "
                                "ORDER BY score "
                                "LIMIT 1"
                            )
                        )
                    except Exception as exc:
                        return PostgresLexicalReadiness(
                            connected=True,
                            backend=self.bm25_backend,
                            pg_textsearch_extension=True,
                            bm25_index=True,
                            bm25_operator=False,
                            detail=f"pg_textsearch BM25 operator smoke query failed: {exc}",
                        )
                    return PostgresLexicalReadiness(
                        connected=True,
                        backend=self.bm25_backend,
                        pg_textsearch_extension=True,
                        bm25_index=True,
                        bm25_operator=True,
                        detail=(
                            "PostgreSQL connection, pg_textsearch BM25 index, "
                            "and BM25 operator are ready."
                        ),
                    )
                if self.bm25_backend == "postgres_fts":
                    index = await session.execute(text("SELECT to_regclass('idx_chunks_text_fts')"))
                    if index.scalar_one_or_none() is None:
                        message = (
                            "Native PostgreSQL FTS index idx_chunks_text_fts "
                            "is not available."
                        )
                        return PostgresLexicalReadiness(
                            connected=True,
                            backend=self.bm25_backend,
                            native_fts_index=False,
                            detail=message,
                        )
                    return PostgresLexicalReadiness(
                        connected=True,
                        backend=self.bm25_backend,
                        native_fts_index=True,
                        detail="PostgreSQL connection and native FTS index are ready.",
                    )
                return PostgresLexicalReadiness(
                    connected=True,
                    backend=self.bm25_backend,
                    detail=f"Unsupported BM25_BACKEND: {self.bm25_backend}",
                )
        except Exception as exc:
            return PostgresLexicalReadiness(
                connected=False,
                backend=self.bm25_backend,
                detail=str(exc),
            )

    async def clear(
        self,
        *,
        system_name: str | None = None,
        kb_name: str | None = None,
    ) -> dict[str, int]:
        """Delete knowledge-base rows from PostgreSQL.

        Args:
            system_name: Optional system scope. When omitted, all rows are
                deleted from the GraphRAG schema tables.
            kb_name: Optional knowledge-base scope within the selected system.

        Returns:
            Mapping of table name to deleted row count.
        """

        counts: dict[str, int] = {}
        ordered_models = [
            RetrievalMetadataModel,
            ArtifactRecordModel,
            CanonicalFactModel,
            IngestionRunModel,
            DeltaModel,
            EntityModel,
            RequirementModel,
            FactModel,
            ChunkModel,
            DocumentVersionModel,
            DocumentModel,
        ]
        async with self.session_factory.begin() as session:
            workflow_filters = _cleanup_filters(WorkflowRunModel, system_name, kb_name)
            workflow_run_ids = await session.execute(
                select(WorkflowRunModel.workflow_run_id).where(*workflow_filters)
            )
            run_ids = list(workflow_run_ids.scalars().all())
            if run_ids:
                result = await session.execute(
                    delete(WorkflowStepModel).where(WorkflowStepModel.workflow_run_id.in_(run_ids))
                )
                counts[WorkflowStepModel.__tablename__] = int(result.rowcount or 0)
            else:
                counts[WorkflowStepModel.__tablename__] = 0
            result = await session.execute(
                delete(WorkflowRunModel).where(*workflow_filters)
            )
            counts[WorkflowRunModel.__tablename__] = int(result.rowcount or 0)
            for model in ordered_models:
                result = await session.execute(
                    delete(model).where(*_cleanup_filters(model, system_name, kb_name))
                )
                counts[model.__tablename__] = int(result.rowcount or 0)
            if system_name is None:
                result = await session.execute(delete(SystemModel))
                counts[SystemModel.__tablename__] = int(result.rowcount or 0)
            elif kb_name is None:
                result = await session.execute(
                    delete(SystemModel).where(SystemModel.system_name == system_name)
                )
                counts[SystemModel.__tablename__] = int(result.rowcount or 0)
        return counts

    async def begin_ingestion_run(self, run: IngestionRunRecord) -> None:
        """Create or update a started ingestion run.

        Args:
            run: Started run record generated by the orchestration agent.
        """

        async with self.session_factory.begin() as session:
            await self._upsert_one(
                session, IngestionRunModel, _run_values(run), ["ingestion_run_id"]
            )

    async def mark_run_succeeded(
        self,
        ingestion_run_id: str,
        *,
        document_id: str,
        document_version_id: str,
    ) -> None:
        """Mark an ingestion run as succeeded.

        Args:
            ingestion_run_id: Run identifier created at ingestion start.
            document_id: Stable document lineage identifier persisted by the run.
            document_version_id: Version identifier persisted by the run.
        """

        async with self.session_factory.begin() as session:
            await session.execute(
                update(IngestionRunModel)
                .where(IngestionRunModel.ingestion_run_id == ingestion_run_id)
                .values(
                    status=IngestionRunStatus.COMPLETED.value,
                    ended_at=datetime.now(UTC),
                    document_id=document_id,
                    document_version_id=document_version_id,
                    error_message=None,
                )
            )

    async def mark_run_stage(
        self,
        ingestion_run_id: str,
        status: IngestionRunStatus,
    ) -> None:
        """Mark an ingestion run stage checkpoint."""

        async with self.session_factory.begin() as session:
            await session.execute(
                update(IngestionRunModel)
                .where(IngestionRunModel.ingestion_run_id == ingestion_run_id)
                .values(status=status.value)
            )

    async def mark_run_failed(self, ingestion_run_id: str, error_message: str) -> None:
        """Mark an ingestion run as failed.

        Args:
            ingestion_run_id: Run identifier created at ingestion start.
            error_message: Failure detail to store for operators.
        """

        async with self.session_factory.begin() as session:
            await session.execute(
                update(IngestionRunModel)
                .where(IngestionRunModel.ingestion_run_id == ingestion_run_id)
                .values(
                    status=IngestionRunStatus.FAILED.value,
                    ended_at=datetime.now(UTC),
                    error_message=error_message,
                )
            )

    async def begin_workflow_run(self, run: WorkflowRunRecord) -> None:
        """Create or update a started workflow run."""

        async with self.session_factory.begin() as session:
            await self._upsert_one(
                session,
                WorkflowRunModel,
                _workflow_run_values(run),
                ["workflow_run_id"],
            )

    async def finish_workflow_run(
        self,
        workflow_run_id: str,
        *,
        status: WorkflowStatus,
        intent_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Mark a workflow run finished."""

        async with self.session_factory.begin() as session:
            await session.execute(
                update(WorkflowRunModel)
                .where(WorkflowRunModel.workflow_run_id == workflow_run_id)
                .values(
                    status=status.value,
                    ended_at=datetime.now(UTC),
                    intent_type=intent_type,
                    error_message=error_message,
                )
            )

    async def record_workflow_step(self, step: WorkflowStepRecord) -> None:
        """Create or update one workflow step audit row."""

        async with self.session_factory.begin() as session:
            await self._upsert_one(
                session,
                WorkflowStepModel,
                _workflow_step_values(step),
                ["workflow_step_id"],
            )

    async def record_artifact(self, record: ArtifactRecord) -> None:
        """Create or update one generated artifact audit row."""

        async with self.session_factory.begin() as session:
            await self._upsert_one(
                session,
                ArtifactRecordModel,
                _artifact_record_values(record),
                ["artifact_id"],
            )

    async def get_active_document_version(
        self,
        *,
        system_name: str,
        kb_name: str,
    ) -> DocumentVersionRecord | None:
        """Return the active version for a system and knowledge base.

        Args:
            system_name: Logical system name.
            kb_name: Knowledge-base name or context.

        Returns:
            Most recent active document version, or ``None`` when no active
            version exists.
        """

        async with self.session_factory() as session:
            result = await session.execute(
                select(DocumentVersionModel)
                .where(
                    DocumentVersionModel.system_name == system_name,
                    DocumentVersionModel.kb_name == kb_name,
                    DocumentVersionModel.status == DocumentStatus.ACTIVE.value,
                )
                .order_by(DocumentVersionModel.created_at.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
        return _document_version_from_model(row) if row else None

    async def list_facts_for_version(self, document_version_id: str) -> list[FactRecord]:
        """List facts for one document version.

        Args:
            document_version_id: Version identifier whose facts should be read.

        Returns:
            Facts ordered by fact key for deterministic delta comparison.
        """

        async with self.session_factory() as session:
            result = await session.execute(
                select(FactModel)
                .where(FactModel.document_version_id == document_version_id)
                .order_by(FactModel.fact_key.asc())
            )
            rows = result.scalars().all()
        return [_fact_from_model(row) for row in rows]

    async def list_chunks_for_version(self, document_version_id: str) -> list[ChunkRecord]:
        """List chunks for one document version.

        Args:
            document_version_id: Version identifier whose chunks should be read.

        Returns:
            Chunks ordered by page and chunk index for deterministic re-indexing.
        """

        async with self.session_factory() as session:
            result = await session.execute(
                select(ChunkModel)
                .where(ChunkModel.document_version_id == document_version_id)
                .order_by(ChunkModel.page.asc(), ChunkModel.chunk_index.asc())
            )
            rows = result.scalars().all()
        return [_chunk_from_model(row) for row in rows]

    async def persist_ingestion(
        self,
        *,
        system: SystemRecord,
        document: DocumentRecord,
        document_version: DocumentVersionRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
        superseded_version_id: str | None,
    ) -> None:
        """Persist the ingestion bundle in one transaction.

        Args:
            system: System record to upsert.
            document: Stable document lineage record to upsert.
            document_version: Newly ingested version record.
            chunks: Text chunks to store and index for retrieval.
            facts: Extracted facts anchored to the stored chunks.
            deltas: Version-to-version fact changes.
            superseded_version_id: Previous active version to mark superseded,
                if a newer valid version was ingested.
        """

        requirements = _requirements_from_facts(facts)
        entities = _entities_from_facts(facts)
        retrieval_metadata = [
            {
                "retrieval_metadata_id": stable_id("retrieval_metadata", chunk.chunk_id),
                "chunk_id": chunk.chunk_id,
                "document_version_id": chunk.document_version_id,
                "system_name": chunk.system_name,
                "kb_name": chunk.kb_name,
                "metadata": {
                    "source_name": chunk.source_name,
                    "page": chunk.page,
                    "section_title": chunk.section_title,
                },
            }
            for chunk in chunks
        ]
        async with self.session_factory.begin() as session:
            await self._upsert_one(session, SystemModel, _system_values(system), ["system_id"])
            await self._upsert_one(
                session, DocumentModel, _document_values(document), ["document_id"]
            )
            if superseded_version_id:
                await self._mark_version_superseded(
                    session,
                    superseded_version_id=superseded_version_id,
                    superseded_by_version_id=document_version.document_version_id,
                )
            await self._upsert_one(
                session,
                DocumentVersionModel,
                _document_version_values(document_version),
                ["document_version_id"],
            )
            await self._upsert_many(
                session, ChunkModel, [_chunk_values(chunk) for chunk in chunks], ["chunk_id"]
            )
            await self._upsert_many(
                session, FactModel, [_fact_values(fact) for fact in facts], ["fact_id"]
            )
            await self._upsert_canonical_facts(
                session,
                _canonical_facts_from_facts(facts),
            )
            await self._upsert_many(
                session,
                RequirementModel,
                [_requirement_values(requirement) for requirement in requirements],
                ["requirement_pk"],
            )
            await self._upsert_many(
                session,
                EntityModel,
                [_entity_values(entity) for entity in entities],
                ["entity_id"],
            )
            await self._upsert_many(
                session, DeltaModel, [_delta_values(delta) for delta in deltas], ["delta_id"]
            )
            await self._upsert_many(
                session, RetrievalMetadataModel, retrieval_metadata, ["retrieval_metadata_id"]
            )

    async def search_chunks(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str,
        version: str | None = None,
        active_only: bool | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Search chunks with the configured lexical ranking backend.

        Args:
            query_text: Query text converted to the configured lexical query.
            system_name: System filter for active chunks.
            kb_name: Knowledge-base filter for active chunks.
            version: Optional version filter.
            active_only: Whether to restrict results to active chunks. When
                omitted, active evidence is used unless a specific version is
                requested.
            top_k: Maximum number of ranked chunks to return.

        Returns:
            Ranked retrieval results with ``bm25`` or ``fts`` as the source signal.
        """

        if self.bm25_backend == "pg_textsearch":
            return await self._search_chunks_pg_textsearch(
                query_text,
                system_name=system_name,
                kb_name=kb_name,
                version=version,
                active_only=active_only,
                top_k=top_k,
            )
        if self.bm25_backend == "postgres_fts":
            return await self._search_chunks_postgres_fts(
                query_text,
                system_name=system_name,
                kb_name=kb_name,
                version=version,
                active_only=active_only,
                top_k=top_k,
            )
        raise ConfigError(f"Unsupported BM25_BACKEND: {self.bm25_backend}")

    async def _search_chunks_pg_textsearch(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str,
        version: str | None,
        active_only: bool | None,
        top_k: int,
    ) -> list[RetrievalResult]:
        bm25_query = func.to_bm25query(
            bindparam("query_text"),
            literal_column("'idx_chunks_text_bm25'"),
        )
        score = ChunkModel.text.op("<@>")(bm25_query).label("score")
        filters = self._chunk_search_filters(
            system_name=system_name,
            kb_name=kb_name,
            version=version,
            active_only=active_only,
            match_expr=score < 0,
        )
        stmt: Select[Any] = (
            select(ChunkModel, score)
            .where(*filters)
            .order_by(score.asc(), ChunkModel.page.asc(), ChunkModel.chunk_index.asc())
            .limit(top_k)
        )
        async with self.session_factory() as session:
            result = await session.execute(stmt, {"query_text": query_text})
            rows = result.all()
        return [
            _retrieval_result_from_chunk_model(
                chunk,
                score=float(score_value or 0.0),
                source="bm25",
            )
            for chunk, score_value in rows
        ]

    async def _search_chunks_postgres_fts(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str,
        version: str | None,
        active_only: bool | None,
        top_k: int,
    ) -> list[RetrievalResult]:
        english_config = literal_column("'english'")
        search_query = func.websearch_to_tsquery(english_config, bindparam("query_text"))
        search_vector = func.to_tsvector(
            english_config,
            func.coalesce(ChunkModel.text, ""),
        )
        match_expr = search_vector.op("@@")(search_query)
        filters = self._chunk_search_filters(
            system_name=system_name,
            kb_name=kb_name,
            version=version,
            active_only=active_only,
            match_expr=match_expr,
        )
        rank = func.ts_rank_cd(search_vector, search_query).label("score")
        stmt: Select[Any] = (
            select(ChunkModel, rank)
            .where(*filters)
            .order_by(rank.desc(), ChunkModel.page.asc(), ChunkModel.chunk_index.asc())
            .limit(top_k)
        )
        async with self.session_factory() as session:
            result = await session.execute(stmt, {"query_text": query_text})
            rows = result.all()
        return [
            _retrieval_result_from_chunk_model(chunk, score=float(score or 0.0), source="fts")
            for chunk, score in rows
        ]

    def _chunk_search_filters(
        self,
        *,
        system_name: str,
        kb_name: str,
        version: str | None,
        active_only: bool | None,
        match_expr: Any,
    ) -> list[Any]:
        filters = [
            ChunkModel.system_name == system_name,
            ChunkModel.kb_name == kb_name,
            match_expr,
        ]
        if active_only is None:
            active_only = version is None
        if active_only:
            active_canonical_fact_exists = (
                select(CanonicalFactModel.canonical_fact_id)
                .join(FactModel, FactModel.fact_id == CanonicalFactModel.active_fact_id)
                .where(
                    FactModel.chunk_id == ChunkModel.chunk_id,
                    CanonicalFactModel.system_name == system_name,
                    CanonicalFactModel.kb_name == kb_name,
                    CanonicalFactModel.status == DocumentStatus.ACTIVE.value,
                )
                .exists()
            )
            filters.append(
                or_(
                    ChunkModel.status == DocumentStatus.ACTIVE.value,
                    active_canonical_fact_exists,
                )
            )
        if version:
            filters.append(ChunkModel.version == version)
        return filters

    async def list_chunks_by_ids(
        self,
        chunk_ids: Sequence[str],
        *,
        active_only: bool = False,
    ) -> list[RetrievalResult]:
        """Return chunks by IDs preserving database metadata.

        Args:
            chunk_ids: Ordered chunk identifiers from graph traversal.
            active_only: Whether to exclude superseded chunks while hydrating
                graph-selected IDs.

        Returns:
            Retrieval results for known chunk IDs, preserving the input order for
            IDs found in PostgreSQL.
        """

        if not chunk_ids:
            return []
        filters = [ChunkModel.chunk_id.in_(chunk_ids)]
        if active_only:
            filters.append(ChunkModel.status == DocumentStatus.ACTIVE.value)
        async with self.session_factory() as session:
            result = await session.execute(select(ChunkModel).where(*filters))
            chunks = result.scalars().all()
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        return [
            _retrieval_result_from_chunk_model(by_id[chunk_id], score=1.0, source="graph")
            for chunk_id in chunk_ids
            if chunk_id in by_id
        ]

    async def _mark_version_superseded(
        self,
        session: AsyncSession,
        *,
        superseded_version_id: str,
        superseded_by_version_id: str,
    ) -> None:
        await session.execute(
            update(DocumentVersionModel)
            .where(DocumentVersionModel.document_version_id == superseded_version_id)
            .values(
                status=DocumentStatus.SUPERSEDED.value,
                superseded_by_version_id=superseded_by_version_id,
                optimistic_lock_version=DocumentVersionModel.optimistic_lock_version + 1,
            )
        )
        for model in (ChunkModel, FactModel, RequirementModel, EntityModel):
            await session.execute(
                update(model)
                .where(model.document_version_id == superseded_version_id)
                .values(status=DocumentStatus.SUPERSEDED.value)
            )

    async def _upsert_one(
        self,
        session: AsyncSession,
        model: Any,
        values: dict[str, Any],
        conflict_columns: list[str],
    ) -> None:
        await self._upsert_many(session, model, [values], conflict_columns)

    async def _upsert_many(
        self,
        session: AsyncSession,
        model: Any,
        rows: list[dict[str, Any]],
        conflict_columns: list[str],
    ) -> None:
        if not rows:
            return
        table = model.__table__
        stmt = pg_insert(table).values(rows)
        update_values = {
            column.name: getattr(stmt.excluded, column.name)
            for column in table.columns
            if column.name not in set(conflict_columns)
        }
        stmt = stmt.on_conflict_do_update(index_elements=conflict_columns, set_=update_values)
        await session.execute(stmt)

    async def _upsert_canonical_facts(
        self,
        session: AsyncSession,
        records: list[CanonicalFactRecord],
    ) -> None:
        rows = [_canonical_fact_values(record) for record in records]
        if not rows:
            return
        table = CanonicalFactModel.__table__
        stmt = pg_insert(table).values(rows)
        update_values = {
            "current_value": stmt.excluded.current_value,
            "status": stmt.excluded.status,
            "active_fact_id": stmt.excluded.active_fact_id,
            "last_confirmed_version_id": stmt.excluded.last_confirmed_version_id,
            "superseded_by_fact_id": stmt.excluded.superseded_by_fact_id,
            "confidence": stmt.excluded.confidence,
            "reasoning_summary": stmt.excluded.reasoning_summary,
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["canonical_fact_id"],
            set_=update_values,
        )
        await session.execute(stmt)


def _system_values(record: SystemRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["metadata"] = payload.pop("metadata")
    return payload


def _document_values(record: DocumentRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["metadata"] = payload.pop("metadata")
    return payload


def _document_version_values(record: DocumentVersionRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["status"] = record.status.value
    payload["metadata"] = payload.pop("metadata")
    return payload


def _chunk_values(record: ChunkRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["status"] = record.status.value
    payload["metadata"] = payload.pop("metadata")
    return payload


def _fact_values(record: FactRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["status"] = record.status.value
    payload["metadata"] = payload.pop("metadata")
    return payload


def _requirement_values(record: RequirementRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["requirement_pk"] = stable_id(
        "requirement",
        record.system_name,
        record.kb_name,
        record.requirement_id,
        record.document_version_id,
    )
    payload["status"] = record.status.value
    payload["metadata"] = payload.pop("metadata")
    return payload


def _entity_values(record: EntityRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["status"] = record.status.value
    payload["metadata"] = payload.pop("metadata")
    return payload


def _delta_values(record: DeltaRecord) -> dict[str, Any]:
    return record.model_dump(mode="python")


def _run_values(record: IngestionRunRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["status"] = record.status.value
    payload["metadata"] = payload.pop("metadata")
    return payload


def _workflow_run_values(record: WorkflowRunRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["status"] = record.status.value
    payload["metadata"] = payload.pop("metadata")
    return payload


def _workflow_step_values(record: WorkflowStepRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["status"] = record.status.value
    payload["metadata"] = payload.pop("metadata")
    return payload


def _artifact_record_values(record: ArtifactRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["metadata"] = payload.pop("metadata")
    return payload


def _canonical_fact_values(record: CanonicalFactRecord) -> dict[str, Any]:
    return record.model_dump(mode="python")


def _cleanup_filters(model: Any, system_name: str | None, kb_name: str | None) -> list[Any]:
    filters = []
    if system_name is not None and hasattr(model, "system_name"):
        filters.append(model.system_name == system_name)
    if kb_name is not None and hasattr(model, "kb_name"):
        filters.append(model.kb_name == kb_name)
    return filters


def _document_version_from_model(row: DocumentVersionModel) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        document_version_id=row.document_version_id,
        document_id=row.document_id,
        system_name=row.system_name,
        kb_name=row.kb_name,
        version=row.version,
        status=DocumentStatus(row.status),
        source_path=row.source_path,
        source_name=row.source_name,
        content_hash=row.content_hash,
        created_at=row.created_at,
        supersedes_version_id=row.supersedes_version_id,
        superseded_by_version_id=row.superseded_by_version_id,
        optimistic_lock_version=row.optimistic_lock_version,
        metadata=row.metadata_json,
    )


def _fact_from_model(row: FactModel) -> FactRecord:
    return FactRecord(
        fact_id=row.fact_id,
        fact_key=row.fact_key,
        fact_type=row.fact_type,
        value=row.value,
        unit=row.unit,
        document_version_id=row.document_version_id,
        document_id=row.document_id,
        chunk_id=row.chunk_id,
        system_name=row.system_name,
        kb_name=row.kb_name,
        version=row.version,
        status=DocumentStatus(row.status),
        evidence=row.evidence,
        requirement_id=row.requirement_id,
        semantic_key=row.semantic_key,
        metadata=row.metadata_json,
    )


def _chunk_from_model(row: ChunkModel) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=row.chunk_id,
        document_version_id=row.document_version_id,
        document_id=row.document_id,
        system_name=row.system_name,
        kb_name=row.kb_name,
        version=row.version,
        status=DocumentStatus(row.status),
        source_name=row.source_name,
        page=row.page,
        section_title=row.section_title,
        chunk_index=row.chunk_index,
        content_hash=row.content_hash,
        text=row.text,
        metadata=row.metadata_json,
    )


def _retrieval_result_from_chunk_model(
    row: ChunkModel,
    *,
    score: float,
    source: str,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        document_version_id=row.document_version_id,
        system_name=row.system_name,
        kb_name=row.kb_name,
        version=row.version,
        source_name=row.source_name,
        page=row.page,
        text=row.text,
        score=score,
        sources=[source],
        metadata=row.metadata_json,
    )


def _requirements_from_facts(facts: list[FactRecord]) -> list[RequirementRecord]:
    requirements: dict[tuple[str, str], RequirementRecord] = {}
    for fact in facts:
        requirement_id = fact.requirement_id if fact.requirement_id else None
        if fact.fact_type == "requirement":
            requirement_id = fact.value
        if not requirement_id:
            continue
        key = (fact.document_version_id, requirement_id)
        requirements[key] = RequirementRecord(
            requirement_id=requirement_id,
            document_version_id=fact.document_version_id,
            document_id=fact.document_id,
            chunk_id=fact.chunk_id,
            system_name=fact.system_name,
            kb_name=fact.kb_name,
            version=fact.version,
            status=fact.status,
            text=fact.evidence,
        )
    return list(requirements.values())


def _entities_from_facts(facts: list[FactRecord]) -> list[EntityRecord]:
    entities: dict[str, EntityRecord] = {}
    for fact in facts:
        entity = _entity_from_fact(fact)
        if entity:
            entities[entity.entity_id] = entity
    return list(entities.values())


def _entity_from_fact(fact: FactRecord) -> EntityRecord | None:
    entity_type = fact.fact_type
    name = fact.value
    if fact.fact_type == "threshold":
        sensor = str(fact.metadata.get("sensor") or "").lower()
        if not sensor:
            return None
        entity_type = "sensor"
        name = sensor
    elif fact.fact_type not in {"sensor", "protocol", "device", "topic"}:
        return None
    return EntityRecord(
        entity_id=stable_id("entity", fact.system_name, fact.kb_name, entity_type, name.lower()),
        entity_type=entity_type,
        name=name,
        document_version_id=fact.document_version_id,
        document_id=fact.document_id,
        chunk_id=fact.chunk_id,
        system_name=fact.system_name,
        kb_name=fact.kb_name,
        version=fact.version,
        status=fact.status,
    )


def _canonical_facts_from_facts(facts: list[FactRecord]) -> list[CanonicalFactRecord]:
    records: dict[str, CanonicalFactRecord] = {}
    for fact in facts:
        semantic_key = fact.semantic_key or fact.fact_key
        canonical_fact_id = stable_id(
            "canonical_fact",
            fact.system_name,
            fact.kb_name,
            semantic_key,
        )
        records[canonical_fact_id] = CanonicalFactRecord(
            canonical_fact_id=canonical_fact_id,
            system_name=fact.system_name,
            kb_name=fact.kb_name,
            semantic_key=semantic_key,
            current_value=fact.value,
            status=DocumentStatus.ACTIVE.value,
            originating_fact_id=fact.fact_id,
            active_fact_id=fact.fact_id,
            originating_version_id=fact.document_version_id,
            last_confirmed_version_id=fact.document_version_id,
            reasoning_summary="deterministic extraction; absent facts are carried forward",
        )
    return list(records.values())
