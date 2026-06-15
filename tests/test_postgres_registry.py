from multi_agentic_rag.models import ChunkRecord, DocumentRecord, DocumentStatus
from multi_agentic_rag.storage.postgres_registry import PostgresRegistry


def test_postgres_registry_initializes_and_upserts_document() -> None:
    connection = FakeConnection()
    registry = PostgresRegistry("postgresql+psycopg://user:pass@host/db")
    registry._connect = lambda: connection  # type: ignore[method-assign]
    document = DocumentRecord(
        document_id="doc_1",
        system_name="PROJECT_1",
        version="v1",
        status=DocumentStatus.ACTIVE,
        source_path="documents/doc.pdf",
        source_name="doc.pdf",
        content_hash="hash_1",
    )

    registry.initialize()
    registry.upsert_document(document)

    sql_text = "\n".join(sql for sql, _ in connection.calls)
    assert "CREATE TABLE IF NOT EXISTS documents" in sql_text
    assert "CREATE TABLE IF NOT EXISTS test_run_results" in sql_text
    assert "INSERT INTO documents" in sql_text
    assert "ON CONFLICT(document_id) DO UPDATE" in sql_text
    assert connection.calls[-1][1]["document_id"] == "doc_1"


def test_postgres_registry_keyword_search_uses_postgres_full_text() -> None:
    row = {
        "chunk_id": "chunk_1",
        "document_id": "doc_1",
        "system_name": "PROJECT_1",
        "version": "v1",
        "status": "active",
        "source_name": "doc.pdf",
        "page": 1,
        "section_title": "Requirements",
        "chunk_index": 0,
        "content_hash": "hash_1",
        "text": "REQ-1 exposes REST GET /api/status.",
        "score": 0.75,
    }
    connection = FakeConnection(rows=[row])
    registry = PostgresRegistry("postgresql://user:pass@host/db")
    registry._connect = lambda: connection  # type: ignore[method-assign]

    results = registry.search_chunks(
        "REST /api/status",
        system_name="PROJECT_1",
        status=DocumentStatus.ACTIVE,
    )

    sql, params = connection.calls[-1]
    assert "to_tsvector('english', text)" in sql
    assert "plainto_tsquery('english', %(query_text)s)" in sql
    assert "system_name = %(system_name)s" in sql
    assert params["query_text"] == "REST /api/status"
    assert results == [row]


def test_postgres_registry_round_trips_chunk_rows_from_dicts() -> None:
    row = {
        "chunk_id": "chunk_1",
        "document_id": "doc_1",
        "system_name": "PROJECT_1",
        "version": "v1",
        "status": "active",
        "source_name": "doc.pdf",
        "page": 1,
        "section_title": "Requirements",
        "chunk_index": 0,
        "content_hash": "hash_1",
        "text": "REQ-1 exposes REST GET /api/status.",
    }
    connection = FakeConnection(rows=[row])
    registry = PostgresRegistry("postgresql://user:pass@host/db")
    registry._connect = lambda: connection  # type: ignore[method-assign]

    chunks = registry.list_chunks(system_name="PROJECT_1")

    assert chunks == [ChunkRecord(**row)]


class FakeConnection:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, sql: str, params=None):
        self.calls.append((sql, params or {}))
        return FakeCursor(self.rows)


class FakeCursor:
    def __init__(self, rows) -> None:
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows
