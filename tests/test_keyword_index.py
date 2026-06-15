from pathlib import Path

from multi_agentic_rag.config import Settings
from multi_agentic_rag.models import ChunkRecord, DocumentRecord, DocumentStatus, FactRecord
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
        registry_provider="sqlite",
        allow_local_dev_mode=True,
        marag_target_mode="local",
        graphrag_required=False,
        neo4j_uri=None,
        vector_store_provider="chroma",
        embedding_provider="hash",
        reranker_provider="none",
        llm_provider="none",
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
    assert "exposes REST GET /api/status and Modbus register 40001" in result.answer
    assert any("no exact extracted fact matched" in warning for warning in result.warnings)


def test_version_label_does_not_force_historical_query(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        registry_provider="sqlite",
        allow_local_dev_mode=True,
        marag_target_mode="local",
        graphrag_required=False,
        neo4j_uri=None,
        vector_store_provider="chroma",
        embedding_provider="hash",
        reranker_provider="none",
        llm_provider="none",
    )
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    document = _document().model_copy(update={"source_name": "SIIMCS_BRD_V1.pdf"})
    chunk = _chunk(document).model_copy(
        update={
            "text": (
                "3. Business Scope\n"
                "3.1 In Scope\n"
                "Controller-based polling of three configured sensors or field instruments."
            ),
        }
    )
    continuation = _chunk(document).model_copy(
        update={
            "chunk_id": "chunk_scope_continuation",
            "chunk_index": 1,
            "text": (
                "Collection of temperature, vibration, gas, pressure, or equivalent "
                "industrial readings.\n"
                "Cloud-based storage and monitoring.\n"
                "3.2 Out of Scope\n"
                "Manufacturing physical sensors."
            ),
        }
    )
    unrelated = _chunk(document).model_copy(
        update={
            "chunk_id": "chunk_unrelated",
            "chunk_index": 2,
            "text": "REQ-1 The temperature threshold maximum is 80 C.",
        }
    )
    v2_document = _document().model_copy(
        update={
            "document_id": "doc_2",
            "source_name": "SIIMCS_BRD_V2.pdf",
        }
    )
    v2_chunk = _chunk(v2_document).model_copy(
        update={
            "chunk_id": "chunk_v2",
            "text": "SIIMCS BRD V2 covered areas include cloud telemetry and MQTT.",
        }
    )

    registry.upsert_document(document)
    registry.upsert_document(v2_document)
    registry.upsert_chunks([chunk, continuation, unrelated])
    registry.upsert_chunks([v2_chunk])
    registry.upsert_facts([_fact(document, unrelated)])

    result = answer_query(
        "What are the covered areas of BRD V1?",
        system_name="SIIMCS",
        version="v1",
        settings=settings,
    )

    assert result.supported
    assert result.evidence
    assert result.intent == "current_truth"
    assert result.evidence[0].chunk_id == chunk.chunk_id
    assert {evidence.chunk_id for evidence in result.evidence} == {
        chunk.chunk_id,
        continuation.chunk_id,
    }
    assert "Controller-based polling" in result.answer
    assert "Cloud-based storage and monitoring" in result.answer
    assert "Manufacturing physical sensors" not in result.answer


def test_threshold_query_uses_table_evidence_not_generic_sensor_facts(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        registry_provider="sqlite",
        allow_local_dev_mode=True,
        marag_target_mode="local",
        graphrag_required=False,
        neo4j_uri=None,
        vector_store_provider="chroma",
        embedding_provider="hash",
        reranker_provider="none",
        llm_provider="none",
    )
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    document = _document().model_copy(update={"source_name": "SIIMCS_BRD_V2.pdf", "version": "v2"})
    chunk = _chunk(document).model_copy(
        update={
            "chunk_id": "chunk_threshold_table",
            "version": "v2",
            "page": 6,
            "text": (
                "6.9 Sensor and Actuator Data Sheet\n"
                "Type\n"
                "Normal Range\n"
                "Min Threshold\n"
                "Max Threshold\n"
                "Critical Level\n"
                "Temperature Sensor\n"
                "10-50°C\n"
                "5-10°C\n"
                "50-70°C\n"
                ">70°C\n"
                "Vibration Sensor\n"
                "1-5 mm/s\n"
                "0-1 mm/s\n"
                "5-8 mm/s\n"
                ">8 mm/s"
            ),
        }
    )
    sensor_fact = FactRecord(
        fact_id="fact_sensor_temperature",
        fact_key="sensor:temperature",
        fact_type="sensor",
        value="temperature",
        document_id=document.document_id,
        chunk_id=chunk.chunk_id,
        system_name=document.system_name,
        version=document.version,
        status=document.status,
        evidence="Temperature Sensor",
    )

    registry.upsert_document(document)
    registry.upsert_chunks([chunk])
    registry.upsert_facts([sensor_fact])

    result = answer_query(
        "Tell me, maximum sensor temperature threshold",
        system_name="SIIMCS",
        version="v2",
        settings=settings,
    )

    assert result.supported
    assert "temperature max threshold = 50-70 C" in result.answer
    assert "temperature critical level = >70 C" in result.answer
    assert "sensor:temperature" not in result.answer
    assert result.evidence[0].chunk_id == chunk.chunk_id


def test_explicit_version_query_can_retrieve_superseded_document(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        registry_provider="sqlite",
        allow_local_dev_mode=True,
        marag_target_mode="local",
        graphrag_required=False,
        neo4j_uri=None,
        vector_store_provider="chroma",
        embedding_provider="hash",
        reranker_provider="none",
        llm_provider="none",
    )
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    document = _document().model_copy(update={"status": DocumentStatus.SUPERSEDED})
    chunk = _chunk(document).model_copy(
        update={
            "status": DocumentStatus.SUPERSEDED,
            "text": "BRD V1 covered areas include sensors, alerts, dashboards, and access control.",
        }
    )

    registry.upsert_document(document)
    registry.upsert_chunks([chunk])

    result = answer_query(
        "What are the covered areas of BRD V1?",
        system_name="SIIMCS",
        version="v1",
        settings=settings,
    )

    assert result.supported
    assert result.intent == "current_truth"
    assert result.evidence[0].chunk_id == chunk.chunk_id
    assert result.evidence[0].version == "v1"


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


def _fact(document: DocumentRecord, chunk: ChunkRecord) -> FactRecord:
    return FactRecord(
        fact_id="fact_1",
        fact_key="threshold:temperature",
        fact_type="threshold",
        value="80",
        unit="C",
        document_id=document.document_id,
        chunk_id=chunk.chunk_id,
        system_name=document.system_name,
        version=document.version,
        status=document.status,
        evidence="temperature threshold maximum is 80 C",
    )
