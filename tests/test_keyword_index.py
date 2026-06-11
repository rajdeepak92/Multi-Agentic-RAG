from pathlib import Path

from multi_agentic_rag.config import Settings
from multi_agentic_rag.models import ChunkRecord, DocumentRecord, DocumentStatus
from multi_agentic_rag.retrieval import answer_query
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry


def test_sqlite_fts_search_finds_requirement_and_protocol_terms(tmp_path: Path) -> None:
    registry = SQLiteRegistry(tmp_path / "registry.db")
    registry.initialize()
    document = _document()
    chunk = _chunk(document)

    registry.upsert_document(document)
    registry.upsert_chunks([chunk])

    results = registry.search_chunks(
        "REQ-42 Modbus register 40001",
        system_name="SIIMCS",
        status=DocumentStatus.ACTIVE,
    )

    assert results
    assert results[0]["chunk_id"] == chunk.chunk_id


def test_sqlite_fts_status_updates_when_document_is_superseded(tmp_path: Path) -> None:
    registry = SQLiteRegistry(tmp_path / "registry.db")
    registry.initialize()
    document = _document()
    chunk = _chunk(document)

    registry.upsert_document(document)
    registry.upsert_chunks([chunk])
    registry.update_document_status(
        document.document_id,
        DocumentStatus.SUPERSEDED,
        superseded_by="doc_2",
    )

    active_results = registry.search_chunks(
        "Modbus register 40001",
        system_name="SIIMCS",
        status=DocumentStatus.ACTIVE,
    )
    superseded_results = registry.search_chunks(
        "Modbus register 40001",
        system_name="SIIMCS",
        status=DocumentStatus.SUPERSEDED,
    )

    assert active_results == []
    assert superseded_results[0]["chunk_id"] == chunk.chunk_id


def test_keyword_evidence_supports_query_when_no_fact_matches(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        neo4j_uri=None,
    )
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    document = _document()
    chunk = _chunk(document)

    registry.upsert_document(document)
    registry.upsert_chunks([chunk])

    result = answer_query(
        "Which evidence mentions REST /api/status and Modbus register 40001?",
        system_name="SIIMCS",
        settings=settings,
    )

    assert result.supported
    assert result.evidence
    assert "keyword" in result.retrieval_sources
    assert "no extracted fact matched exactly" in result.answer


def _document() -> DocumentRecord:
    return DocumentRecord(
        document_id="doc_1",
        system_name="SIIMCS",
        version="v1",
        status=DocumentStatus.ACTIVE,
        source_path="brd.pdf",
        source_name="brd.pdf",
        content_hash="filehash",
    )


def _chunk(document: DocumentRecord) -> ChunkRecord:
    return ChunkRecord(
        chunk_id="chunk_1",
        document_id=document.document_id,
        system_name=document.system_name,
        version=document.version,
        status=document.status,
        source_name=document.source_name,
        page=1,
        section_title="Interfaces",
        chunk_index=0,
        content_hash="chunkhash",
        text="REQ-42 Gateway GW-1 exposes REST GET /api/status and Modbus register 40001.",
    )
