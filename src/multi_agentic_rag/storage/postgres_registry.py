"""PostgreSQL implementation of the metadata registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from multi_agentic_rag.models import (
    ChunkRecord,
    CoverageRecord,
    CoverageRunRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    FactRecord,
    GeneratedTestFileRecord,
    TestRunResultRecord,
)


class PostgresRegistry:
    """PostgreSQL registry for strict target GraphRAG runtime metadata."""

    def __init__(self, dsn: str) -> None:
        self.dsn = _normalize_dsn(dsn)
        self.db_path = Path("postgresql")

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency check
            raise RuntimeError(
                "REGISTRY_PROVIDER=postgresql requires psycopg. Run `uv sync --locked`."
            ) from exc
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def initialize(self) -> None:
        """Create registry tables and indexes if missing."""

        with self._connect() as connection:
            connection.execute(
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
                CREATE INDEX IF NOT EXISTS idx_chunks_text_fts
                    ON chunks USING GIN (to_tsvector('english', text));

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
                    semantic_key TEXT,
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
                    evidence_json TEXT NOT NULL,
                    document_id TEXT,
                    version TEXT,
                    chunk_id TEXT,
                    fact_id TEXT,
                    semantic_key TEXT,
                    impact_status TEXT DEFAULT 'new_required',
                    lifecycle_status TEXT DEFAULT 'active',
                    previous_coverage_id TEXT,
                    superseded_by TEXT,
                    scenario_index INTEGER,
                    source_hash TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_coverage_requirement
                    ON coverage(requirement_id);

                CREATE TABLE IF NOT EXISTS coverage_runs (
                    run_id TEXT PRIMARY KEY,
                    system_name TEXT NOT NULL,
                    version TEXT,
                    scope_hash TEXT NOT NULL,
                    scenario_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    generated_count INTEGER NOT NULL,
                    coverage_ids_json TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_coverage_runs_scope
                    ON coverage_runs(system_name, version, scope_hash, scenario_count);

                CREATE TABLE IF NOT EXISTS generated_test_files (
                    test_file_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    system_name TEXT NOT NULL,
                    version TEXT,
                    scope_hash TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    tracking_file_path TEXT,
                    robot_file_path TEXT,
                    coverage_report_path TEXT,
                    report_file_paths_json TEXT NOT NULL DEFAULT '[]',
                    harness_file_paths_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    coverage_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_generated_test_files_scope
                    ON generated_test_files(system_name, version, scope_hash);

                CREATE TABLE IF NOT EXISTS test_run_results (
                    result_id TEXT PRIMARY KEY,
                    test_file_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    system_name TEXT NOT NULL,
                    version TEXT,
                    file_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    exit_code INTEGER,
                    passed INTEGER NOT NULL,
                    failed INTEGER NOT NULL,
                    skipped INTEGER NOT NULL,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    failure_category TEXT,
                    failure_reason TEXT,
                    dependency_blockers_json TEXT NOT NULL,
                    execution_scope TEXT NOT NULL DEFAULT 'all',
                    xml_report_path TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    output TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_test_run_results_file
                    ON test_run_results(test_file_id, created_at);
                """
            )

    def upsert_document(self, document: DocumentRecord) -> None:
        self._upsert(
            "documents",
            document.model_dump(mode="json"),
            [
                "document_id",
                "system_name",
                "version",
                "status",
                "source_path",
                "source_name",
                "content_hash",
                "created_at",
                "supersedes",
                "superseded_by",
            ],
            conflict="document_id",
        )

    def get_document(self, document_id: str) -> DocumentRecord | None:
        row = self._fetch_one(
            "SELECT * FROM documents WHERE document_id = %(document_id)s",
            {"document_id": document_id},
        )
        return self._document_from_row(row) if row else None

    def get_active_document(self, system_name: str) -> DocumentRecord | None:
        row = self._fetch_one(
            """
            SELECT * FROM documents
            WHERE system_name = %(system_name)s AND status = %(status)s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"system_name": system_name, "status": DocumentStatus.ACTIVE.value},
        )
        return self._document_from_row(row) if row else None

    def list_documents(
        self,
        *,
        system_name: str | None = None,
        status: DocumentStatus | None = None,
    ) -> list[DocumentRecord]:
        query, params = self._select_with_filters(
            "documents",
            [
                ("system_name", system_name),
                ("status", status.value if status else None),
            ],
            order_by="created_at ASC",
        )
        return [self._document_from_row(row) for row in self._fetch_all(query, params)]

    def update_document_status(
        self,
        document_id: str,
        status: DocumentStatus,
        *,
        superseded_by: str | None = None,
    ) -> None:
        params = {
            "document_id": document_id,
            "status": status.value,
            "superseded_by": superseded_by,
        }
        with self._connect() as connection:
            if superseded_by:
                connection.execute(
                    """
                    UPDATE documents
                    SET status = %(status)s, superseded_by = %(superseded_by)s
                    WHERE document_id = %(document_id)s
                    """,
                    params,
                )
            else:
                connection.execute(
                    """
                    UPDATE documents SET status = %(status)s
                    WHERE document_id = %(document_id)s
                    """,
                    params,
                )
            connection.execute(
                """
                UPDATE chunks SET status = %(status)s
                WHERE document_id = %(document_id)s
                """,
                params,
            )
            connection.execute(
                """
                UPDATE facts SET status = %(status)s
                WHERE document_id = %(document_id)s
                """,
                params,
            )

    def upsert_chunks(self, chunks: list[ChunkRecord]) -> None:
        if not chunks:
            return
        columns = [
            "chunk_id",
            "document_id",
            "system_name",
            "version",
            "status",
            "source_name",
            "page",
            "section_title",
            "chunk_index",
            "content_hash",
            "text",
        ]
        self._upsert_many("chunks", [chunk.model_dump(mode="json") for chunk in chunks], columns, "chunk_id")

    def list_chunks(
        self,
        *,
        system_name: str | None = None,
        version: str | None = None,
        status: DocumentStatus | None = None,
        document_id: str | None = None,
    ) -> list[ChunkRecord]:
        query, params = self._select_with_filters(
            "chunks",
            [
                ("system_name", system_name),
                ("version", version),
                ("status", status.value if status else None),
                ("document_id", document_id),
            ],
            order_by="page ASC, chunk_index ASC",
        )
        return [ChunkRecord(**_row_dict(row)) for row in self._fetch_all(query, params)]

    def search_chunks(
        self,
        query_text: str,
        *,
        system_name: str | None = None,
        version: str | None = None,
        status: DocumentStatus | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search chunks with PostgreSQL full-text ranking."""

        if not query_text.strip():
            return []
        filters = ["to_tsvector('english', text) @@ plainto_tsquery('english', %(query_text)s)"]
        params: dict[str, Any] = {"query_text": query_text, "top_k": top_k}
        self._append_filter(filters, params, "system_name", system_name)
        self._append_filter(filters, params, "version", version)
        self._append_filter(filters, params, "status", status.value if status else None)
        sql = f"""
            SELECT
                chunk_id,
                document_id,
                system_name,
                version,
                status,
                source_name,
                page,
                section_title,
                chunk_index,
                content_hash,
                text,
                ts_rank_cd(
                    to_tsvector('english', text),
                    plainto_tsquery('english', %(query_text)s)
                ) AS score
            FROM chunks
            WHERE {" AND ".join(filters)}
            ORDER BY score DESC, page ASC, chunk_index ASC
            LIMIT %(top_k)s
        """
        try:
            return [_row_dict(row) for row in self._fetch_all(sql, params)]
        except Exception:
            return []

    def upsert_facts(self, facts: list[FactRecord]) -> None:
        if not facts:
            return
        rows = []
        for fact in facts:
            payload = fact.model_dump(mode="json")
            payload["metadata_json"] = json.dumps(payload.pop("metadata"), sort_keys=True)
            rows.append(payload)
        self._upsert_many(
            "facts",
            rows,
            [
                "fact_id",
                "fact_key",
                "fact_type",
                "value",
                "unit",
                "document_id",
                "chunk_id",
                "system_name",
                "version",
                "status",
                "evidence",
                "requirement_id",
                "semantic_key",
                "metadata_json",
            ],
            "fact_id",
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
        query, params = self._select_with_filters(
            "facts",
            [
                ("system_name", system_name),
                ("version", version),
                ("status", status.value if status else None),
                ("document_id", document_id),
                ("fact_key", fact_key),
            ],
            order_by="fact_key ASC, version ASC",
        )
        return [self._fact_from_row(row) for row in self._fetch_all(query, params)]

    def insert_deltas(self, deltas: list[DeltaRecord]) -> None:
        if not deltas:
            return
        rows = []
        for delta in deltas:
            payload = delta.model_dump(mode="json")
            payload["evidence_json"] = json.dumps(payload.pop("evidence"), sort_keys=True)
            rows.append(payload)
        self._upsert_many(
            "deltas",
            rows,
            [
                "delta_id",
                "system_name",
                "from_version",
                "to_version",
                "fact_key",
                "change_type",
                "change_magnitude",
                "old_value",
                "new_value",
                "affected_requirement_id",
                "risk_level",
                "evidence_json",
            ],
            "delta_id",
        )

    def list_deltas(
        self,
        *,
        system_name: str | None = None,
        from_version: str | None = None,
        to_version: str | None = None,
    ) -> list[DeltaRecord]:
        query, params = self._select_with_filters(
            "deltas",
            [
                ("system_name", system_name),
                ("from_version", from_version),
                ("to_version", to_version),
            ],
            order_by="delta_id ASC",
        )
        return [self._delta_from_row(row) for row in self._fetch_all(query, params)]

    def upsert_coverage(self, records: list[CoverageRecord]) -> None:
        if not records:
            return
        rows = []
        for record in records:
            payload = record.model_dump(mode="json")
            payload["evidence_json"] = json.dumps(payload.pop("evidence"), sort_keys=True)
            rows.append(payload)
        self._upsert_many(
            "coverage",
            rows,
            [
                "coverage_id",
                "requirement_id",
                "use_case",
                "test_scenario",
                "automation_feasibility",
                "priority",
                "coverage_status",
                "evidence_json",
                "document_id",
                "version",
                "chunk_id",
                "fact_id",
                "semantic_key",
                "impact_status",
                "lifecycle_status",
                "previous_coverage_id",
                "superseded_by",
                "scenario_index",
                "source_hash",
            ],
            "coverage_id",
        )

    def list_coverage(self, *, requirement_id: str | None = None) -> list[CoverageRecord]:
        query, params = self._select_with_filters(
            "coverage",
            [("requirement_id", requirement_id)],
            order_by="requirement_id ASC",
        )
        return [self._coverage_from_row(row) for row in self._fetch_all(query, params)]

    def list_coverage_by_ids(self, coverage_ids: list[str]) -> list[CoverageRecord]:
        if not coverage_ids:
            return []
        rows = self._fetch_all(
            "SELECT * FROM coverage WHERE coverage_id = ANY(%(coverage_ids)s)",
            {"coverage_ids": coverage_ids},
        )
        by_id = {row["coverage_id"]: self._coverage_from_row(row) for row in rows}
        return [by_id[coverage_id] for coverage_id in coverage_ids if coverage_id in by_id]

    def upsert_coverage_run(self, record: CoverageRunRecord) -> None:
        payload = record.model_dump(mode="json")
        payload["coverage_ids_json"] = json.dumps(payload.pop("coverage_ids"), sort_keys=True)
        self._upsert(
            "coverage_runs",
            payload,
            [
                "run_id",
                "system_name",
                "version",
                "scope_hash",
                "scenario_count",
                "status",
                "generated_count",
                "coverage_ids_json",
                "message",
                "created_at",
                "updated_at",
            ],
            conflict="run_id",
            update_columns=[
                "system_name",
                "version",
                "scope_hash",
                "scenario_count",
                "status",
                "generated_count",
                "coverage_ids_json",
                "message",
                "updated_at",
            ],
        )

    def find_coverage_run(
        self,
        *,
        system_name: str,
        version: str | None,
        scope_hash: str,
        scenario_count: int,
        status: str | None = None,
    ) -> CoverageRunRecord | None:
        filters = [
            "system_name = %(system_name)s",
            "scope_hash = %(scope_hash)s",
            "scenario_count = %(scenario_count)s",
        ]
        params: dict[str, Any] = {
            "system_name": system_name,
            "scope_hash": scope_hash,
            "scenario_count": scenario_count,
        }
        if version is None:
            filters.append("version IS NULL")
        else:
            filters.append("version = %(version)s")
            params["version"] = version
        if status:
            filters.append("status = %(status)s")
            params["status"] = status
        row = self._fetch_one(
            f"""
            SELECT * FROM coverage_runs
            WHERE {" AND ".join(filters)}
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            params,
        )
        return self._coverage_run_from_row(row) if row else None

    def upsert_generated_test_file(self, record: GeneratedTestFileRecord) -> None:
        payload = record.model_dump(mode="json")
        payload["coverage_ids_json"] = json.dumps(payload.pop("coverage_ids"), sort_keys=True)
        payload["report_file_paths_json"] = json.dumps(
            payload.pop("report_file_paths"),
            sort_keys=True,
        )
        payload["harness_file_paths_json"] = json.dumps(
            payload.pop("harness_file_paths"),
            sort_keys=True,
        )
        self._upsert(
            "generated_test_files",
            payload,
            [
                "test_file_id",
                "run_id",
                "system_name",
                "version",
                "scope_hash",
                "file_path",
                "tracking_file_path",
                "robot_file_path",
                "coverage_report_path",
                "report_file_paths_json",
                "harness_file_paths_json",
                "status",
                "coverage_ids_json",
                "created_at",
                "updated_at",
            ],
            conflict="test_file_id",
            update_columns=[
                "run_id",
                "system_name",
                "version",
                "scope_hash",
                "file_path",
                "tracking_file_path",
                "robot_file_path",
                "coverage_report_path",
                "report_file_paths_json",
                "harness_file_paths_json",
                "status",
                "coverage_ids_json",
                "updated_at",
            ],
        )

    def find_generated_test_file(
        self,
        *,
        system_name: str,
        version: str | None,
        scope_hash: str,
    ) -> GeneratedTestFileRecord | None:
        filters = ["system_name = %(system_name)s", "scope_hash = %(scope_hash)s"]
        params: dict[str, Any] = {"system_name": system_name, "scope_hash": scope_hash}
        if version is None:
            filters.append("version IS NULL")
        else:
            filters.append("version = %(version)s")
            params["version"] = version
        row = self._fetch_one(
            f"""
            SELECT * FROM generated_test_files
            WHERE {" AND ".join(filters)}
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            params,
        )
        return self._generated_test_file_from_row(row) if row else None

    def get_generated_test_file(self, test_file_id: str) -> GeneratedTestFileRecord | None:
        row = self._fetch_one(
            "SELECT * FROM generated_test_files WHERE test_file_id = %(test_file_id)s",
            {"test_file_id": test_file_id},
        )
        return self._generated_test_file_from_row(row) if row else None

    def insert_test_run_result(self, record: TestRunResultRecord) -> None:
        payload = record.model_dump(mode="json")
        payload["dependency_blockers_json"] = json.dumps(
            payload.pop("dependency_blockers"),
            sort_keys=True,
        )
        self._upsert(
            "test_run_results",
            payload,
            [
                "result_id",
                "test_file_id",
                "run_id",
                "system_name",
                "version",
                "file_path",
                "status",
                "exit_code",
                "passed",
                "failed",
                "skipped",
                "blocked",
                "failure_category",
                "failure_reason",
                "dependency_blockers_json",
                "execution_scope",
                "xml_report_path",
                "duration_seconds",
                "output",
                "created_at",
            ],
            conflict="result_id",
            update_columns=[
                "status",
                "exit_code",
                "passed",
                "failed",
                "skipped",
                "blocked",
                "failure_category",
                "failure_reason",
                "dependency_blockers_json",
                "execution_scope",
                "xml_report_path",
                "duration_seconds",
                "output",
            ],
        )

    def get_latest_test_result(
        self,
        *,
        system_name: str,
        version: str | None = None,
    ) -> TestRunResultRecord | None:
        filters = ["system_name = %(system_name)s"]
        params: dict[str, Any] = {"system_name": system_name}
        if version is None:
            filters.append("version IS NULL")
        else:
            filters.append("version = %(version)s")
            params["version"] = version
        row = self._fetch_one(
            f"""
            SELECT * FROM test_run_results
            WHERE {" AND ".join(filters)}
            ORDER BY created_at DESC
            LIMIT 1
            """,
            params,
        )
        return self._test_run_result_from_row(row) if row else None

    def _upsert(
        self,
        table: str,
        payload: dict[str, Any],
        columns: list[str],
        *,
        conflict: str,
        update_columns: list[str] | None = None,
    ) -> None:
        update_columns = update_columns or [column for column in columns if column != conflict]
        sql = _upsert_sql(table, columns, conflict=conflict, update_columns=update_columns)
        with self._connect() as connection:
            connection.execute(sql, payload)

    def _upsert_many(
        self,
        table: str,
        rows: list[dict[str, Any]],
        columns: list[str],
        conflict: str,
    ) -> None:
        sql = _upsert_sql(
            table,
            columns,
            conflict=conflict,
            update_columns=[column for column in columns if column != conflict],
        )
        with self._connect() as connection:
            for row in rows:
                connection.execute(sql, row)

    def _fetch_one(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return _row_dict(row) if row else None

    def _fetch_all(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_row_dict(row) for row in rows]

    @staticmethod
    def _select_with_filters(
        table: str,
        filters: list[tuple[str, Any]],
        *,
        order_by: str,
    ) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        for column, value in filters:
            if value is None:
                continue
            clauses.append(f"{column} = %({column})s")
            params[column] = value
        query = f"SELECT * FROM {table}"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += f" ORDER BY {order_by}"
        return query, params

    @staticmethod
    def _append_filter(
        filters: list[str],
        params: dict[str, Any],
        column: str,
        value: Any,
    ) -> None:
        if value is None:
            return
        filters.append(f"{column} = %({column})s")
        params[column] = value

    @staticmethod
    def _document_from_row(row: dict[str, Any]) -> DocumentRecord:
        return DocumentRecord(**_row_dict(row))

    @staticmethod
    def _fact_from_row(row: dict[str, Any]) -> FactRecord:
        payload = _row_dict(row)
        payload["metadata"] = json.loads(payload.pop("metadata_json") or "{}")
        return FactRecord(**payload)

    @staticmethod
    def _delta_from_row(row: dict[str, Any]) -> DeltaRecord:
        payload = _row_dict(row)
        payload["evidence"] = json.loads(payload.pop("evidence_json") or "[]")
        return DeltaRecord(**payload)

    @staticmethod
    def _coverage_from_row(row: dict[str, Any]) -> CoverageRecord:
        payload = _row_dict(row)
        payload["evidence"] = json.loads(payload.pop("evidence_json") or "[]")
        payload["impact_status"] = payload.get("impact_status") or "new_required"
        payload["lifecycle_status"] = payload.get("lifecycle_status") or "active"
        return CoverageRecord(**payload)

    @staticmethod
    def _coverage_run_from_row(row: dict[str, Any]) -> CoverageRunRecord:
        payload = _row_dict(row)
        payload["coverage_ids"] = json.loads(payload.pop("coverage_ids_json") or "[]")
        return CoverageRunRecord(**payload)

    @staticmethod
    def _generated_test_file_from_row(row: dict[str, Any]) -> GeneratedTestFileRecord:
        payload = _row_dict(row)
        payload["coverage_ids"] = json.loads(payload.pop("coverage_ids_json") or "[]")
        payload["report_file_paths"] = json.loads(
            payload.pop("report_file_paths_json", "[]") or "[]"
        )
        payload["harness_file_paths"] = json.loads(
            payload.pop("harness_file_paths_json", "[]") or "[]"
        )
        return GeneratedTestFileRecord(**payload)

    @staticmethod
    def _test_run_result_from_row(row: dict[str, Any]) -> TestRunResultRecord:
        payload = _row_dict(row)
        payload["dependency_blockers"] = json.loads(
            payload.pop("dependency_blockers_json") or "[]"
        )
        payload["blocked"] = payload.get("blocked") or 0
        payload["execution_scope"] = payload.get("execution_scope") or "all"
        payload["duration_seconds"] = payload.get("duration_seconds") or 0.0
        return TestRunResultRecord(**payload)


def _upsert_sql(
    table: str,
    columns: list[str],
    *,
    conflict: str,
    update_columns: list[str],
) -> str:
    column_text = ", ".join(columns)
    value_text = ", ".join(f"%({column})s" for column in columns)
    update_text = ", ".join(f"{column}=excluded.{column}" for column in update_columns)
    return f"""
        INSERT INTO {table} ({column_text})
        VALUES ({value_text})
        ON CONFLICT({conflict}) DO UPDATE SET {update_text}
    """


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def _normalize_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)
