"""SQLite implementation of the metadata registry."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from multi_agentic_rag.models import (
    ChunkRecord,
    CoverageRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    FactRecord,
)
from multi_agentic_rag.utils.paths import resolve_path


class SQLiteRegistry:
    """Embedded SQLite registry for documents, chunks, facts, deltas, and coverage."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = resolve_path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        """Create registry tables if missing."""

        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    system_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    supersedes TEXT,
                    superseded_by TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_documents_system
                    ON documents(system_name);
                CREATE INDEX IF NOT EXISTS idx_documents_status
                    ON documents(status);
                CREATE INDEX IF NOT EXISTS idx_documents_version
                    ON documents(version);

                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    system_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    page INTEGER NOT NULL,
                    section_title TEXT,
                    chunk_index INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_chunks_document
                    ON chunks(document_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_system_status
                    ON chunks(system_name, status);
                CREATE INDEX IF NOT EXISTS idx_chunks_version
                    ON chunks(version);

                CREATE TABLE IF NOT EXISTS facts (
                    fact_id TEXT PRIMARY KEY,
                    fact_key TEXT NOT NULL,
                    fact_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    unit TEXT,
                    document_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    system_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    requirement_id TEXT,
                    metadata_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_facts_system_status
                    ON facts(system_name, status);
                CREATE INDEX IF NOT EXISTS idx_facts_key
                    ON facts(fact_key);
                CREATE INDEX IF NOT EXISTS idx_facts_version
                    ON facts(version);

                CREATE TABLE IF NOT EXISTS deltas (
                    delta_id TEXT PRIMARY KEY,
                    system_name TEXT NOT NULL,
                    from_version TEXT NOT NULL,
                    to_version TEXT NOT NULL,
                    fact_key TEXT,
                    change_type TEXT NOT NULL,
                    change_magnitude TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    affected_requirement_id TEXT,
                    risk_level TEXT NOT NULL,
                    evidence_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_deltas_system
                    ON deltas(system_name);
                CREATE INDEX IF NOT EXISTS idx_deltas_versions
                    ON deltas(from_version, to_version);

                CREATE TABLE IF NOT EXISTS coverage (
                    coverage_id TEXT PRIMARY KEY,
                    requirement_id TEXT NOT NULL,
                    use_case TEXT NOT NULL,
                    test_scenario TEXT NOT NULL,
                    automation_feasibility TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    coverage_status TEXT NOT NULL,
                    evidence_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_coverage_requirement
                    ON coverage(requirement_id);
                """
            )
            self._ensure_column(connection, "deltas", "fact_key", "TEXT")

    def upsert_document(self, document: DocumentRecord) -> None:
        payload = document.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    document_id, system_name, version, status, source_path, source_name,
                    content_hash, created_at, supersedes, superseded_by
                )
                VALUES (
                    :document_id, :system_name, :version, :status, :source_path, :source_name,
                    :content_hash, :created_at, :supersedes, :superseded_by
                )
                ON CONFLICT(document_id) DO UPDATE SET
                    system_name=excluded.system_name,
                    version=excluded.version,
                    status=excluded.status,
                    source_path=excluded.source_path,
                    source_name=excluded.source_name,
                    content_hash=excluded.content_hash,
                    created_at=excluded.created_at,
                    supersedes=excluded.supersedes,
                    superseded_by=excluded.superseded_by
                """,
                payload,
            )

    def get_document(self, document_id: str) -> DocumentRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return self._document_from_row(row) if row else None

    def get_active_document(self, system_name: str) -> DocumentRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM documents
                WHERE system_name = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (system_name, DocumentStatus.ACTIVE.value),
            ).fetchone()
        return self._document_from_row(row) if row else None

    def list_documents(
        self,
        *,
        system_name: str | None = None,
        status: DocumentStatus | None = None,
    ) -> list[DocumentRecord]:
        query = "SELECT * FROM documents"
        filters: list[str] = []
        params: list[Any] = []
        if system_name:
            filters.append("system_name = ?")
            params.append(system_name)
        if status:
            filters.append("status = ?")
            params.append(status.value)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY created_at ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._document_from_row(row) for row in rows]

    def update_document_status(
        self,
        document_id: str,
        status: DocumentStatus,
        *,
        superseded_by: str | None = None,
    ) -> None:
        with self._connect() as connection:
            if superseded_by:
                connection.execute(
                    """
                    UPDATE documents
                    SET status = ?, superseded_by = ?
                    WHERE document_id = ?
                    """,
                    (status.value, superseded_by, document_id),
                )
            else:
                connection.execute(
                    "UPDATE documents SET status = ? WHERE document_id = ?",
                    (status.value, document_id),
                )
            connection.execute(
                "UPDATE chunks SET status = ? WHERE document_id = ?",
                (status.value, document_id),
            )
            connection.execute(
                "UPDATE facts SET status = ? WHERE document_id = ?",
                (status.value, document_id),
            )

    def upsert_chunks(self, chunks: list[ChunkRecord]) -> None:
        if not chunks:
            return
        rows = [chunk.model_dump(mode="json") for chunk in chunks]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO chunks (
                    chunk_id, document_id, system_name, version, status, source_name,
                    page, section_title, chunk_index, content_hash, text
                )
                VALUES (
                    :chunk_id, :document_id, :system_name, :version, :status, :source_name,
                    :page, :section_title, :chunk_index, :content_hash, :text
                )
                ON CONFLICT(chunk_id) DO UPDATE SET
                    document_id=excluded.document_id,
                    system_name=excluded.system_name,
                    version=excluded.version,
                    status=excluded.status,
                    source_name=excluded.source_name,
                    page=excluded.page,
                    section_title=excluded.section_title,
                    chunk_index=excluded.chunk_index,
                    content_hash=excluded.content_hash,
                    text=excluded.text
                """,
                rows,
            )

    def list_chunks(
        self,
        *,
        system_name: str | None = None,
        version: str | None = None,
        status: DocumentStatus | None = None,
        document_id: str | None = None,
    ) -> list[ChunkRecord]:
        query = "SELECT * FROM chunks"
        filters: list[str] = []
        params: list[Any] = []
        if system_name:
            filters.append("system_name = ?")
            params.append(system_name)
        if version:
            filters.append("version = ?")
            params.append(version)
        if status:
            filters.append("status = ?")
            params.append(status.value)
        if document_id:
            filters.append("document_id = ?")
            params.append(document_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY page ASC, chunk_index ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [ChunkRecord(**dict(row)) for row in rows]

    def upsert_facts(self, facts: list[FactRecord]) -> None:
        if not facts:
            return
        rows = []
        for fact in facts:
            payload = fact.model_dump(mode="json")
            payload["metadata_json"] = json.dumps(payload.pop("metadata"), sort_keys=True)
            rows.append(payload)
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO facts (
                    fact_id, fact_key, fact_type, value, unit, document_id, chunk_id,
                    system_name, version, status, evidence, requirement_id, metadata_json
                )
                VALUES (
                    :fact_id, :fact_key, :fact_type, :value, :unit, :document_id, :chunk_id,
                    :system_name, :version, :status, :evidence, :requirement_id, :metadata_json
                )
                ON CONFLICT(fact_id) DO UPDATE SET
                    fact_key=excluded.fact_key,
                    fact_type=excluded.fact_type,
                    value=excluded.value,
                    unit=excluded.unit,
                    document_id=excluded.document_id,
                    chunk_id=excluded.chunk_id,
                    system_name=excluded.system_name,
                    version=excluded.version,
                    status=excluded.status,
                    evidence=excluded.evidence,
                    requirement_id=excluded.requirement_id,
                    metadata_json=excluded.metadata_json
                """,
                rows,
            )

    def list_facts(
        self,
        *,
        system_name: str | None = None,
        version: str | None = None,
        status: DocumentStatus | None = None,
        document_id: str | None = None,
        fact_key: str | None = None,
    ) -> list[FactRecord]:
        query = "SELECT * FROM facts"
        filters: list[str] = []
        params: list[Any] = []
        if system_name:
            filters.append("system_name = ?")
            params.append(system_name)
        if version:
            filters.append("version = ?")
            params.append(version)
        if status:
            filters.append("status = ?")
            params.append(status.value)
        if document_id:
            filters.append("document_id = ?")
            params.append(document_id)
        if fact_key:
            filters.append("fact_key = ?")
            params.append(fact_key)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY fact_key ASC, version ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._fact_from_row(row) for row in rows]

    def insert_deltas(self, deltas: list[DeltaRecord]) -> None:
        if not deltas:
            return
        rows = []
        for delta in deltas:
            payload = delta.model_dump(mode="json")
            payload["evidence_json"] = json.dumps(payload.pop("evidence"), sort_keys=True)
            rows.append(payload)
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO deltas (
                    delta_id, system_name, from_version, to_version, fact_key, change_type,
                    change_magnitude, old_value, new_value, affected_requirement_id,
                    risk_level, evidence_json
                )
                VALUES (
                    :delta_id, :system_name, :from_version, :to_version, :fact_key, :change_type,
                    :change_magnitude, :old_value, :new_value, :affected_requirement_id,
                    :risk_level, :evidence_json
                )
                ON CONFLICT(delta_id) DO UPDATE SET
                    system_name=excluded.system_name,
                    from_version=excluded.from_version,
                    to_version=excluded.to_version,
                    fact_key=excluded.fact_key,
                    change_type=excluded.change_type,
                    change_magnitude=excluded.change_magnitude,
                    old_value=excluded.old_value,
                    new_value=excluded.new_value,
                    affected_requirement_id=excluded.affected_requirement_id,
                    risk_level=excluded.risk_level,
                    evidence_json=excluded.evidence_json
                """,
                rows,
            )

    def list_deltas(
        self,
        *,
        system_name: str | None = None,
        from_version: str | None = None,
        to_version: str | None = None,
    ) -> list[DeltaRecord]:
        query = "SELECT * FROM deltas"
        filters: list[str] = []
        params: list[Any] = []
        if system_name:
            filters.append("system_name = ?")
            params.append(system_name)
        if from_version:
            filters.append("from_version = ?")
            params.append(from_version)
        if to_version:
            filters.append("to_version = ?")
            params.append(to_version)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY delta_id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._delta_from_row(row) for row in rows]

    def upsert_coverage(self, records: list[CoverageRecord]) -> None:
        if not records:
            return
        rows = []
        for record in records:
            payload = record.model_dump(mode="json")
            payload["evidence_json"] = json.dumps(payload.pop("evidence"), sort_keys=True)
            rows.append(payload)
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO coverage (
                    coverage_id, requirement_id, use_case, test_scenario,
                    automation_feasibility, priority, coverage_status, evidence_json
                )
                VALUES (
                    :coverage_id, :requirement_id, :use_case, :test_scenario,
                    :automation_feasibility, :priority, :coverage_status, :evidence_json
                )
                ON CONFLICT(coverage_id) DO UPDATE SET
                    requirement_id=excluded.requirement_id,
                    use_case=excluded.use_case,
                    test_scenario=excluded.test_scenario,
                    automation_feasibility=excluded.automation_feasibility,
                    priority=excluded.priority,
                    coverage_status=excluded.coverage_status,
                    evidence_json=excluded.evidence_json
                """,
                rows,
            )

    def list_coverage(self, *, requirement_id: str | None = None) -> list[CoverageRecord]:
        query = "SELECT * FROM coverage"
        params: list[Any] = []
        if requirement_id:
            query += " WHERE requirement_id = ?"
            params.append(requirement_id)
        query += " ORDER BY requirement_id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._coverage_from_row(row) for row in rows]

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
            )

    @staticmethod
    def _document_from_row(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(**dict(row))

    @staticmethod
    def _fact_from_row(row: sqlite3.Row) -> FactRecord:
        payload = dict(row)
        payload["metadata"] = json.loads(payload.pop("metadata_json") or "{}")
        return FactRecord(**payload)

    @staticmethod
    def _delta_from_row(row: sqlite3.Row) -> DeltaRecord:
        payload = dict(row)
        payload["evidence"] = json.loads(payload.pop("evidence_json") or "[]")
        return DeltaRecord(**payload)

    @staticmethod
    def _coverage_from_row(row: sqlite3.Row) -> CoverageRecord:
        payload = dict(row)
        payload["evidence"] = json.loads(payload.pop("evidence_json") or "[]")
        return CoverageRecord(**payload)
