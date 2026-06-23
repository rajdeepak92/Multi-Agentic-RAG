# mypy: ignore-errors
"""Async PostgreSQL repository."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar

from sqlalchemy import Select, bindparam, delete, func, literal_column, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
)
from sqlalchemy.exc import (
    TimeoutError as SQLAlchemyTimeoutError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import (
    ArtifactRecord,
    CanonicalFactRecord,
    ChunkRecord,
    DeltaRecord,
    DocumentCoverageRecord,
    DocumentRecord,
    DocumentStatus,
    DocumentVersionRecord,
    EntityRecord,
    EvidencePackRecord,
    FactRecord,
    IngestionRunRecord,
    IngestionRunStatus,
    RequirementCandidateRecord,
    RequirementConflictRecord,
    RequirementCoverageRecord,
    RequirementCoverageStatus,
    RequirementDiscoveryResult,
    RequirementEvidenceRecord,
    RequirementRecord,
    RequirementType,
    RetrievalHitRecord,
    RetrievalResult,
    RetrievalRunRecord,
    ReviewEventRecord,
    SourceSegmentRecord,
    SystemRecord,
    TraceManifestRecord,
    WorkflowRunRecord,
    WorkflowStatus,
    WorkflowStepRecord,
)
from multi_agentic_rag.exceptions import ConfigError, PersistenceError
from multi_agentic_rag.extraction.rule_extractors import extract_requirement_ledger_from_chunks
from multi_agentic_rag.infrastructure.postgres.models import (
    ArtifactRecordModel,
    CanonicalFactModel,
    ChunkModel,
    DeltaModel,
    DocumentCoverageModel,
    DocumentModel,
    DocumentVersionModel,
    EntityModel,
    EvidencePackModel,
    FactModel,
    IngestionRunModel,
    RequirementCandidateModel,
    RequirementConflictModel,
    RequirementCoverageModel,
    RequirementEvidenceModel,
    RequirementModel,
    RetrievalHitModel,
    RetrievalMetadataModel,
    RetrievalRunModel,
    ReviewEventModel,
    SourceSegmentModel,
    SystemModel,
    TraceManifestModel,
    WorkflowRunModel,
    WorkflowStepModel,
)
from multi_agentic_rag.infrastructure.postgres.session import create_async_session_factory
from multi_agentic_rag.utils.hashing import stable_id

BM25Backend = Literal["pg_textsearch", "postgres_fts"]
T = TypeVar("T")


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
        bm25_backend: BM25Backend = "postgres_fts",
        retry_count: int = 0,
        retry_backoff_seconds: float = 0.0,
    ) -> None:
        """Initialize the repository with an async session factory.

        Args:
            session_factory: Callable that opens an ``AsyncSession`` or
                transaction-scoped async session context.
            bm25_backend: Lexical search backend. ``pg_textsearch`` uses the
                BM25 extension and ``postgres_fts`` uses native PostgreSQL FTS.
            retry_count: Number of retries for transient PostgreSQL failures.
            retry_backoff_seconds: Base backoff between transient retries.
        """

        self.session_factory = session_factory
        self.bm25_backend = bm25_backend
        self.retry_count = max(0, retry_count)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)

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
            retry_count=settings.postgres_retry_count,
            retry_backoff_seconds=settings.postgres_retry_backoff_seconds,
        )

    async def check_connection(self) -> tuple[bool, str]:
        """Verify PostgreSQL connectivity and configured lexical index availability."""

        readiness = await self.check_lexical_readiness()
        return readiness.ready, readiness.detail

    async def _run_with_retry(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        operation_name: str,
    ) -> T:
        """Run one PostgreSQL operation with bounded transient retries."""

        attempt = 0
        while True:
            try:
                return await operation()
            except Exception as exc:
                if attempt >= self.retry_count or not _is_transient_postgres_error(exc):
                    if attempt > 0 and _is_transient_postgres_error(exc):
                        raise PersistenceError(
                            f"PostgreSQL operation {operation_name} failed after "
                            f"{attempt + 1} attempts: {exc}"
                        ) from exc
                    raise
                delay = self.retry_backoff_seconds * (2**attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
                attempt += 1

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
            TraceManifestModel,
            ReviewEventModel,
            EvidencePackModel,
            RetrievalHitModel,
            RetrievalRunModel,
            RetrievalMetadataModel,
            ArtifactRecordModel,
            CanonicalFactModel,
            IngestionRunModel,
            DeltaModel,
            EntityModel,
            RequirementConflictModel,
            DocumentCoverageModel,
            RequirementCandidateModel,
            SourceSegmentModel,
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
            requirement_filters = _cleanup_filters(RequirementModel, system_name, kb_name)
            requirement_pks = await session.execute(
                select(RequirementModel.requirement_pk).where(*requirement_filters)
            )
            scoped_requirement_pks = list(requirement_pks.scalars().all())
            for model in (RequirementCoverageModel, RequirementEvidenceModel):
                if scoped_requirement_pks:
                    result = await session.execute(
                        delete(model).where(model.requirement_pk.in_(scoped_requirement_pks))
                    )
                    counts[model.__tablename__] = int(result.rowcount or 0)
                else:
                    counts[model.__tablename__] = 0
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

    async def record_review_event(self, record: ReviewEventRecord) -> None:
        """Create or update one review event row."""

        async with self.session_factory.begin() as session:
            await self._upsert_one(
                session,
                ReviewEventModel,
                _review_event_values(record),
                ["review_event_id"],
            )

    async def record_retrieval_run(
        self,
        run: RetrievalRunRecord,
        hits: list[RetrievalHitRecord] | None = None,
    ) -> None:
        """Create or update a retrieval run and its hits."""

        async with self.session_factory.begin() as session:
            await self._upsert_one(
                session,
                RetrievalRunModel,
                _retrieval_run_values(run),
                ["retrieval_run_id"],
            )
            await self._upsert_many(
                session,
                RetrievalHitModel,
                [_retrieval_hit_values(hit) for hit in hits or []],
                ["retrieval_hit_id"],
            )

    async def record_evidence_pack(self, record: EvidencePackRecord) -> None:
        """Create or update one evidence pack row."""

        async with self.session_factory.begin() as session:
            await self._upsert_one(
                session,
                EvidencePackModel,
                _evidence_pack_values(record),
                ["evidence_pack_id"],
            )

    async def record_trace_manifest(self, record: TraceManifestRecord) -> None:
        """Create or update one trace manifest row."""

        async with self.session_factory.begin() as session:
            await self._upsert_one(
                session,
                TraceManifestModel,
                _trace_manifest_values(record),
                ["trace_manifest_id"],
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

    async def list_chunks_for_scope(
        self,
        *,
        system_name: str,
        kb_name: str,
        version: str,
        active_only: bool = True,
    ) -> list[ChunkRecord]:
        """List chunks for one system/kb/version scope.

        This is used by operational reindexing paths that need all chunks in a
        version scope, including directory ingests that can contain multiple
        source documents with the same version label.
        """

        filters = [
            ChunkModel.system_name == system_name,
            ChunkModel.kb_name == kb_name,
            ChunkModel.version == version,
        ]
        if active_only:
            filters.append(ChunkModel.status == DocumentStatus.ACTIVE.value)
        async def load() -> list[ChunkModel]:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(ChunkModel)
                    .where(*filters)
                    .order_by(
                        ChunkModel.source_name.asc(),
                        ChunkModel.page.asc(),
                        ChunkModel.chunk_index.asc(),
                    )
                )
                return list(result.scalars().all())

        rows = await self._run_with_retry(load, operation_name="list_chunks_for_scope")
        return [_chunk_from_model(row) for row in rows]

    async def list_requirements_for_scope(
        self,
        *,
        system_name: str,
        kb_name: str,
        version: str,
        requirement_types: set[RequirementType] | None = None,
        active_only: bool = True,
        coverage_required: bool | None = None,
    ) -> list[RequirementRecord]:
        """Enumerate the exact version-scoped requirement ledger."""

        filters = [
            RequirementModel.system_name == system_name,
            RequirementModel.kb_name == kb_name,
            RequirementModel.version == version,
        ]
        if active_only:
            filters.append(RequirementModel.status == DocumentStatus.ACTIVE.value)
        if coverage_required is not None:
            filters.append(RequirementModel.coverage_required == coverage_required)
        if requirement_types:
            filters.append(
                RequirementModel.requirement_type.in_(
                    sorted(requirement_type.value for requirement_type in requirement_types)
                )
            )
        async def load() -> list[RequirementModel]:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(RequirementModel)
                    .where(*filters)
                    .order_by(
                        RequirementModel.requirement_type.asc(),
                        RequirementModel.category.asc().nulls_last(),
                        RequirementModel.canonical_id.asc().nulls_last(),
                        RequirementModel.page.asc().nulls_last(),
                        RequirementModel.requirement_id.asc(),
                    )
                )
                return list(result.scalars().all())

        rows = await self._run_with_retry(
            load,
            operation_name="list_requirements_for_scope",
        )
        return [_requirement_from_model(row) for row in rows]

    async def list_requirement_evidence(
        self,
        *,
        requirement_pks: Sequence[str] | None = None,
    ) -> list[RequirementEvidenceRecord]:
        """List evidence spans for requirement primary keys."""

        filters = []
        if requirement_pks is not None:
            if not requirement_pks:
                return []
            filters.append(RequirementEvidenceModel.requirement_pk.in_(list(requirement_pks)))

        async def load() -> list[RequirementEvidenceModel]:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(RequirementEvidenceModel)
                    .where(*filters)
                    .order_by(
                        RequirementEvidenceModel.page.asc(),
                        RequirementEvidenceModel.chunk_id.asc(),
                        RequirementEvidenceModel.start_offset.asc().nulls_last(),
                    )
                )
                return list(result.scalars().all())

        rows = await self._run_with_retry(load, operation_name="list_requirement_evidence")
        return [_requirement_evidence_from_model(row) for row in rows]

    async def count_requirements_by_type(
        self,
        *,
        system_name: str,
        kb_name: str,
        version: str,
        active_only: bool = True,
    ) -> dict[RequirementType, int]:
        """Count ledger records by canonical requirement type."""

        filters = [
            RequirementModel.system_name == system_name,
            RequirementModel.kb_name == kb_name,
            RequirementModel.version == version,
        ]
        if active_only:
            filters.append(RequirementModel.status == DocumentStatus.ACTIVE.value)
        known_types = {item.value for item in RequirementType}

        async def load() -> list[Any]:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(RequirementModel.requirement_type, func.count())
                    .where(*filters)
                    .group_by(RequirementModel.requirement_type)
                )
                return list(result.all())

        rows = await self._run_with_retry(load, operation_name="count_requirements_by_type")
        return {
            RequirementType(row[0]): int(row[1])
            for row in rows
            if row[0] in known_types
        }

    async def list_uncovered_requirements(
        self,
        *,
        system_name: str,
        kb_name: str,
        version: str,
    ) -> list[RequirementRecord]:
        """Return coverage-required requirements without accepted coverage."""

        covered_statuses = {
            RequirementCoverageStatus.COVERED.value,
            RequirementCoverageStatus.PARTIALLY_COVERED.value,
            RequirementCoverageStatus.DEFERRED.value,
            RequirementCoverageStatus.NOT_APPLICABLE.value,
        }
        coverage_subquery = (
            select(RequirementCoverageModel.requirement_pk)
            .where(RequirementCoverageModel.coverage_status.in_(covered_statuses))
            .subquery()
        )

        async def load() -> list[RequirementModel]:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(RequirementModel)
                    .where(
                        RequirementModel.system_name == system_name,
                        RequirementModel.kb_name == kb_name,
                        RequirementModel.version == version,
                        RequirementModel.status == DocumentStatus.ACTIVE.value,
                        RequirementModel.coverage_required.is_(True),
                        RequirementModel.requirement_pk.not_in(
                            select(coverage_subquery.c.requirement_pk)
                        ),
                    )
                    .order_by(
                        RequirementModel.requirement_type.asc(),
                        RequirementModel.category.asc().nulls_last(),
                        RequirementModel.canonical_id.asc().nulls_last(),
                    )
                )
                return list(result.scalars().all())

        rows = await self._run_with_retry(load, operation_name="list_uncovered_requirements")
        return [_requirement_from_model(row) for row in rows]

    async def upsert_requirement_coverage(
        self,
        records: list[RequirementCoverageRecord],
    ) -> None:
        """Replace and persist deterministic requirement-to-story coverage rows."""

        if not records:
            return

        async def persist() -> None:
            async with self.session_factory.begin() as session:
                requirement_pks = sorted({record.requirement_pk for record in records})
                await session.execute(
                    delete(RequirementCoverageModel).where(
                        RequirementCoverageModel.requirement_pk.in_(requirement_pks)
                    )
                )
                await self._upsert_many(
                    session,
                    RequirementCoverageModel,
                    [_requirement_coverage_values(record) for record in records],
                    ["coverage_id"],
                )

        await self._run_with_retry(persist, operation_name="upsert_requirement_coverage")

    async def rebuild_requirement_ledger_for_scope(
        self,
        *,
        system_name: str,
        kb_name: str,
        version: str,
        active_only: bool = True,
    ) -> tuple[int, int]:
        """Rebuild requirement ledger rows from already stored chunks."""

        filters = [
            ChunkModel.system_name == system_name,
            ChunkModel.kb_name == kb_name,
            ChunkModel.version == version,
        ]
        if active_only:
            filters.append(ChunkModel.status == DocumentStatus.ACTIVE.value)

        async def load_chunks() -> list[ChunkModel]:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(ChunkModel)
                    .where(*filters)
                    .order_by(ChunkModel.page.asc(), ChunkModel.chunk_index.asc())
                )
                return list(result.scalars().all())

        chunk_rows = await self._run_with_retry(
            load_chunks,
            operation_name="rebuild_requirement_ledger_for_scope.load_chunks",
        )
        chunks = [_chunk_from_model(row) for row in chunk_rows]
        requirements, evidence = extract_requirement_ledger_from_chunks(chunks)

        async def persist() -> None:
            async with self.session_factory.begin() as session:
                aligned_requirements, aligned_evidence = await _align_existing_requirement_keys(
                    session,
                    requirements,
                    evidence,
                )
                await self._upsert_many(
                    session,
                    RequirementModel,
                    [_requirement_values(requirement) for requirement in aligned_requirements],
                    ["requirement_pk"],
                )
                await _delete_requirement_evidence_for_requirements(session, aligned_requirements)
                await self._upsert_many(
                    session,
                    RequirementEvidenceModel,
                    [_requirement_evidence_values(item) for item in aligned_evidence],
                    ["requirement_evidence_id"],
                )
                requirements[:] = aligned_requirements
                evidence[:] = aligned_evidence

        await self._run_with_retry(
            persist,
            operation_name="rebuild_requirement_ledger_for_scope.persist",
        )
        return len(requirements), len(evidence)

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
        requirement_discovery_result: RequirementDiscoveryResult | None = None,
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

        discovery = requirement_discovery_result or RequirementDiscoveryResult(
            discovery_id=stable_id(
                "requirement_discovery",
                document_version.document_version_id,
                "not-run",
            ),
            document_version_id=document_version.document_version_id,
            document_id=document.document_id,
            system_name=document.system_name,
            kb_name=document.kb_name,
            version=document_version.version,
        )
        requirements = list(discovery.requirements)
        requirement_evidence = list(discovery.requirement_evidence)
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

        async def persist() -> None:
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
                    session,
                    SourceSegmentModel,
                    [_source_segment_values(segment) for segment in discovery.segments],
                    ["segment_id"],
                )
                await self._upsert_many(
                    session, FactModel, [_fact_values(fact) for fact in facts], ["fact_id"]
                )
                await self._upsert_canonical_facts(
                    session,
                    _canonical_facts_from_facts(facts),
                )
                aligned_requirements, aligned_evidence = await _align_existing_requirement_keys(
                    session,
                    requirements,
                    requirement_evidence,
                )
                await self._upsert_many(
                    session,
                    RequirementModel,
                    [_requirement_values(requirement) for requirement in aligned_requirements],
                    ["requirement_pk"],
                )
                await _delete_requirement_evidence_for_requirements(session, aligned_requirements)
                await self._upsert_many(
                    session,
                    RequirementEvidenceModel,
                    [_requirement_evidence_values(item) for item in aligned_evidence],
                    ["requirement_evidence_id"],
                )
                await self._upsert_many(
                    session,
                    RequirementCandidateModel,
                    [
                        _requirement_candidate_values(candidate)
                        for candidate in discovery.candidates
                    ],
                    ["candidate_id"],
                )
                await self._upsert_many(
                    session,
                    DocumentCoverageModel,
                    [_document_coverage_values(item) for item in discovery.coverage],
                    ["coverage_inventory_id"],
                )
                await self._upsert_many(
                    session,
                    RequirementConflictModel,
                    [_requirement_conflict_values(item) for item in discovery.conflicts],
                    ["conflict_id"],
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

        await self._run_with_retry(persist, operation_name="persist_ingestion")

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
        async def search() -> list[Any]:
            async with self.session_factory() as session:
                result = await session.execute(stmt, {"query_text": query_text})
                return list(result.all())

        rows = await self._run_with_retry(search, operation_name="search_chunks_pg_textsearch")
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
        async def search() -> list[Any]:
            async with self.session_factory() as session:
                result = await session.execute(stmt, {"query_text": query_text})
                return list(result.all())

        rows = await self._run_with_retry(search, operation_name="search_chunks_postgres_fts")
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
        async def load() -> list[ChunkModel]:
            async with self.session_factory() as session:
                result = await session.execute(select(ChunkModel).where(*filters))
                return list(result.scalars().all())

        chunks = await self._run_with_retry(load, operation_name="list_chunks_by_ids")
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
            if column.name not in set(conflict_columns) and column.name != "created_at"
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


def _source_segment_values(record: SourceSegmentRecord) -> dict[str, Any]:
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
    canonical_id = record.canonical_id or record.requirement_id
    payload["requirement_pk"] = record.requirement_pk or stable_id(
        "requirement",
        record.system_name,
        record.kb_name,
        record.version,
        canonical_id,
        record.document_version_id,
    )
    payload["canonical_id"] = canonical_id
    payload["requirement_type"] = record.requirement_type.value
    payload["status"] = record.status.value
    payload["normalized_text"] = record.normalized_text or _normalize_text(record.text)
    payload["semantic_key"] = record.semantic_key or stable_id(
        "requirement_semantic_key",
        record.system_name,
        record.kb_name,
        record.version,
        record.requirement_type.value,
        canonical_id,
        payload["normalized_text"],
    )
    payload["metadata"] = payload.pop("metadata")
    return payload


async def _align_existing_requirement_keys(
    session: AsyncSession,
    requirements: list[RequirementRecord],
    evidence: list[RequirementEvidenceRecord],
) -> tuple[list[RequirementRecord], list[RequirementEvidenceRecord]]:
    if not requirements:
        return requirements, evidence
    keys = [
        (
            requirement.system_name,
            requirement.kb_name,
            requirement.requirement_id,
            requirement.document_version_id,
        )
        for requirement in requirements
    ]
    existing_result = await session.execute(
        select(RequirementModel).where(
            or_(
                *[
                    (
                        (RequirementModel.system_name == system_name)
                        & (RequirementModel.kb_name == kb_name)
                        & (RequirementModel.requirement_id == requirement_id)
                        & (RequirementModel.document_version_id == document_version_id)
                    )
                    for system_name, kb_name, requirement_id, document_version_id in keys
                ]
            )
        )
    )
    existing_by_key = {
        (
            row.system_name,
            row.kb_name,
            row.requirement_id,
            row.document_version_id,
        ): row.requirement_pk
        for row in existing_result.scalars().all()
    }
    pk_replacements: dict[str, str] = {}
    pk_by_unique_key: dict[tuple[str, str, str, str], str] = {}
    aligned_requirements: list[RequirementRecord] = []
    for requirement in requirements:
        unique_key = (
            requirement.system_name,
            requirement.kb_name,
            requirement.requirement_id,
            requirement.document_version_id,
        )
        old_pk = requirement.requirement_pk or stable_id(
            "requirement",
            requirement.system_name,
            requirement.kb_name,
            requirement.version,
            requirement.canonical_id or requirement.requirement_id,
            requirement.document_version_id,
        )
        canonical_pk = existing_by_key.get(unique_key) or pk_by_unique_key.get(unique_key) or old_pk
        pk_by_unique_key[unique_key] = canonical_pk
        if canonical_pk != old_pk:
            pk_replacements[old_pk] = canonical_pk
            aligned_requirements.append(
                requirement.model_copy(update={"requirement_pk": canonical_pk})
            )
        else:
            aligned_requirements.append(requirement)
    requirements_by_pk: dict[str, RequirementRecord] = {}
    for requirement in aligned_requirements:
        if requirement.requirement_pk:
            requirements_by_pk.setdefault(requirement.requirement_pk, requirement)
    aligned_requirements = list(requirements_by_pk.values())
    aligned_evidence: list[RequirementEvidenceRecord] = []
    for item in evidence:
        replacement_pk = pk_replacements.get(item.requirement_pk)
        if not replacement_pk:
            aligned_evidence.append(item)
            continue
        aligned_evidence.append(
            item.model_copy(
                update={
                    "requirement_pk": replacement_pk,
                    "requirement_evidence_id": stable_id(
                        "requirement_evidence",
                        replacement_pk,
                        item.chunk_id,
                        item.start_offset,
                        item.end_offset,
                        item.evidence_text,
                    ),
                }
            )
        )
    return aligned_requirements, aligned_evidence


async def _delete_requirement_evidence_for_requirements(
    session: AsyncSession,
    requirements: Sequence[RequirementRecord],
) -> None:
    requirement_pks = [record.requirement_pk for record in requirements if record.requirement_pk]
    if not requirement_pks:
        return
    await session.execute(
        delete(RequirementEvidenceModel).where(
            RequirementEvidenceModel.requirement_pk.in_(requirement_pks)
        )
    )


def _requirement_evidence_values(record: RequirementEvidenceRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["metadata"] = payload.pop("metadata")
    return payload


def _requirement_candidate_values(record: RequirementCandidateRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["status"] = record.status.value
    payload["requirement_type"] = record.requirement_type.value
    payload["metadata"] = payload.pop("metadata")
    return payload


def _document_coverage_values(record: DocumentCoverageRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["coverage_status"] = record.coverage_status.value
    payload["metadata"] = payload.pop("metadata")
    return payload


def _requirement_conflict_values(record: RequirementConflictRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["status"] = record.status.value
    payload["metadata"] = payload.pop("metadata")
    return payload


def _requirement_coverage_values(record: RequirementCoverageRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["coverage_status"] = record.coverage_status.value
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


def _retrieval_run_values(record: RetrievalRunRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["metadata"] = payload.pop("metadata")
    return payload


def _retrieval_hit_values(record: RetrievalHitRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["metadata"] = payload.pop("metadata")
    return payload


def _evidence_pack_values(record: EvidencePackRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["metadata"] = payload.pop("metadata")
    return payload


def _review_event_values(record: ReviewEventRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="python")
    payload["severity"] = record.severity.value
    return payload


def _trace_manifest_values(record: TraceManifestRecord) -> dict[str, Any]:
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


def _requirement_from_model(row: RequirementModel) -> RequirementRecord:
    return RequirementRecord(
        requirement_pk=row.requirement_pk,
        canonical_id=row.canonical_id or row.requirement_id,
        requirement_id=row.requirement_id,
        requirement_type=RequirementType(row.requirement_type),
        category=row.category,
        title=row.title,
        document_version_id=row.document_version_id,
        document_id=row.document_id,
        chunk_id=row.chunk_id,
        system_name=row.system_name,
        kb_name=row.kb_name,
        version=row.version,
        status=DocumentStatus(row.status),
        text=row.text,
        normalized_text=row.normalized_text,
        source_name=row.source_name,
        page=row.page,
        section_title=row.section_title,
        story_driving=row.story_driving,
        coverage_required=row.coverage_required,
        extraction_method=row.extraction_method,
        confidence=row.confidence,
        semantic_key=row.semantic_key,
        metadata=row.metadata_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _requirement_evidence_from_model(
    row: RequirementEvidenceModel,
) -> RequirementEvidenceRecord:
    return RequirementEvidenceRecord(
        requirement_evidence_id=row.requirement_evidence_id,
        requirement_pk=row.requirement_pk,
        chunk_id=row.chunk_id,
        document_version_id=row.document_version_id,
        source_name=row.source_name,
        page=row.page,
        section_title=row.section_title,
        start_offset=row.start_offset,
        end_offset=row.end_offset,
        evidence_text=row.evidence_text,
        extraction_method=row.extraction_method,
        confidence=row.confidence,
        metadata=row.metadata_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _retrieval_result_from_chunk_model(
    row: ChunkModel,
    *,
    score: float,
    source: str,
) -> RetrievalResult:
    metadata = dict(row.metadata_json)
    metadata[f"{source}_score"] = score
    if source in {"bm25", "fts"}:
        metadata["lexical_score"] = score
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
        metadata=metadata,
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
            normalized_text=_normalize_text(fact.evidence),
            source_name=None,
            page=None,
            section_title=None,
            extraction_method="fact_projection",
            metadata={"source": "facts"},
        )
    return list(requirements.values())


def _requirement_evidence_from_requirements(
    requirements: list[RequirementRecord],
    chunks: list[ChunkRecord],
) -> list[RequirementEvidenceRecord]:
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    evidence: list[RequirementEvidenceRecord] = []
    for requirement in requirements:
        requirement_pk = requirement.requirement_pk or stable_id(
            "requirement",
            requirement.system_name,
            requirement.kb_name,
            requirement.version,
            requirement.canonical_id or requirement.requirement_id,
            requirement.document_version_id,
        )
        chunk = chunks_by_id.get(requirement.chunk_id)
        evidence.append(
            RequirementEvidenceRecord(
                requirement_evidence_id=stable_id(
                    "requirement_evidence",
                    requirement_pk,
                    requirement.chunk_id,
                    _normalize_text(requirement.text),
                ),
                requirement_pk=requirement_pk,
                chunk_id=requirement.chunk_id,
                document_version_id=requirement.document_version_id,
                source_name=chunk.source_name if chunk else requirement.source_name or "",
                page=chunk.page if chunk else requirement.page or 1,
                section_title=chunk.section_title if chunk else requirement.section_title,
                evidence_text=requirement.text,
                extraction_method=requirement.extraction_method,
                confidence=requirement.confidence,
                metadata={"source": "requirement_projection"},
            )
        )
    return evidence


def _normalize_text(text_value: str) -> str:
    import re

    return re.sub(r"\s+", " ", text_value).strip().lower()


_NON_RETRYABLE_POSTGRES_MARKERS = (
    "authentication failed",
    "password authentication failed",
    "invalid password",
    "permission denied",
    "invalid sql",
    "syntax error",
    "undefined table",
    "undefined column",
    "undefined function",
    "relation ",
    "column ",
    "function ",
    "schema ",
    "extension ",
    "pg_textsearch",
    "idx_chunks_text_bm25",
    "constraint",
)
_TRANSIENT_POSTGRES_MARKERS = (
    "connection reset",
    "connection refused",
    "connection is closed",
    "server closed the connection",
    "terminating connection",
    "timeout",
    "timed out",
    "temporarily unavailable",
    "too many connections",
    "deadlock detected",
    "could not serialize access",
    "serialization failure",
)
_TRANSIENT_ORIG_NAMES = (
    "cannotconnectnowerror",
    "connectiondoesnotexisterror",
    "connectionfailureerror",
    "deadlockdetectederror",
    "serializationerror",
    "toomanyconnectionserror",
)


def _is_transient_postgres_error(exc: Exception) -> bool:
    """Return whether a PostgreSQL exception is safe to retry."""

    if isinstance(exc, ProgrammingError | IntegrityError):
        return False
    message = str(exc).lower()
    if any(marker in message for marker in _NON_RETRYABLE_POSTGRES_MARKERS):
        return False
    if isinstance(exc, OperationalError | InterfaceError | SQLAlchemyTimeoutError):
        return True
    if isinstance(exc, DBAPIError):
        original = getattr(exc, "orig", None)
        original_name = type(original).__name__.lower()
        if any(marker in original_name for marker in _TRANSIENT_ORIG_NAMES):
            return True
    return any(marker in message for marker in _TRANSIENT_POSTGRES_MARKERS)


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
