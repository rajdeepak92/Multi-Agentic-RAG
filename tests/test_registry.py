from pathlib import Path

from multi_agentic_rag.delta import compute_fact_deltas
from multi_agentic_rag.models import (
    ChunkRecord,
    DocumentRecord,
    DocumentStatus,
    FactRecord,
)
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry


def test_sqlite_registry_creation(tmp_path: Path) -> None:
    db_path = tmp_path / "registry.db"
    registry = SQLiteRegistry(db_path)
    registry.initialize()

    assert db_path.exists()


def test_document_status_transition_and_no_hard_delete(tmp_path: Path) -> None:
    registry = SQLiteRegistry(tmp_path / "registry.db")
    registry.initialize()
    doc_v1 = _document("doc_v1", "v1", "hash1")
    doc_v2 = _document("doc_v2", "v2", "hash2", supersedes="doc_v1")

    registry.upsert_document(doc_v1)
    registry.upsert_chunks([_chunk(doc_v1, "chunk_v1", "80")])
    registry.upsert_facts([_threshold_fact(doc_v1, "chunk_v1", "80")])
    registry.upsert_document(doc_v2)
    registry.upsert_chunks([_chunk(doc_v2, "chunk_v2", "95")])
    registry.upsert_facts([_threshold_fact(doc_v2, "chunk_v2", "95")])
    registry.update_document_status("doc_v1", DocumentStatus.SUPERSEDED, superseded_by="doc_v2")

    active = registry.get_active_document("SIIMCS")
    all_documents = registry.list_documents(system_name="SIIMCS")
    superseded_chunks = registry.list_chunks(status=DocumentStatus.SUPERSEDED)

    assert active is not None
    assert active.version == "v2"
    assert len(all_documents) == 2
    assert registry.get_document("doc_v1").status == DocumentStatus.SUPERSEDED
    assert superseded_chunks[0].chunk_id == "chunk_v1"


def test_v1_to_v5_latest_value_behavior(tmp_path: Path) -> None:
    registry = SQLiteRegistry(tmp_path / "registry.db")
    registry.initialize()
    doc_v1 = _document("doc_v1", "v1", "hash1")
    doc_v5 = _document("doc_v5", "v5", "hash5", supersedes="doc_v1")
    old_fact = _threshold_fact(doc_v1, "chunk_v1", "80")
    new_fact = _threshold_fact(doc_v5, "chunk_v5", "95")

    registry.upsert_document(doc_v1)
    registry.upsert_chunks([_chunk(doc_v1, "chunk_v1", "80")])
    registry.upsert_facts([old_fact])
    registry.upsert_document(doc_v5)
    registry.upsert_chunks([_chunk(doc_v5, "chunk_v5", "95")])
    registry.upsert_facts([new_fact])
    registry.insert_deltas(
        compute_fact_deltas(
            system_name="SIIMCS",
            from_version="v1",
            to_version="v5",
            old_facts=[old_fact],
            new_facts=[new_fact],
        )
    )
    registry.update_document_status("doc_v1", DocumentStatus.SUPERSEDED, superseded_by="doc_v5")

    active_facts = registry.list_facts(system_name="SIIMCS", status=DocumentStatus.ACTIVE)
    superseded_facts = registry.list_facts(system_name="SIIMCS", status=DocumentStatus.SUPERSEDED)
    deltas = registry.list_deltas(system_name="SIIMCS", from_version="v1", to_version="v5")

    assert [fact.value for fact in active_facts if fact.fact_key == "threshold:temperature"] == ["95"]
    assert [fact.value for fact in superseded_facts if fact.fact_key == "threshold:temperature"] == [
        "80"
    ]
    assert deltas[0].old_value == "80 C"
    assert deltas[0].new_value == "95 C"
    assert len(registry.list_documents(system_name="SIIMCS")) == 2


def _document(
    document_id: str,
    version: str,
    content_hash: str,
    supersedes: str | None = None,
) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        system_name="SIIMCS",
        version=version,
        status=DocumentStatus.ACTIVE,
        source_path=f"brd_{version}.pdf",
        source_name=f"brd_{version}.pdf",
        content_hash=content_hash,
        supersedes=supersedes,
    )


def _chunk(document: DocumentRecord, chunk_id: str, value: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        document_id=document.document_id,
        system_name=document.system_name,
        version=document.version,
        status=DocumentStatus.ACTIVE,
        source_name=document.source_name,
        page=1,
        section_title="Thresholds",
        chunk_index=0,
        content_hash=f"chunk-{value}",
        text=f"REQ-1 temperature threshold is {value} C.",
    )


def _threshold_fact(document: DocumentRecord, chunk_id: str, value: str) -> FactRecord:
    return FactRecord(
        fact_id=f"fact_{document.version}_{value}",
        fact_key="threshold:temperature",
        fact_type="threshold",
        value=value,
        unit="C",
        document_id=document.document_id,
        chunk_id=chunk_id,
        system_name=document.system_name,
        version=document.version,
        status=DocumentStatus.ACTIVE,
        evidence=f"temperature threshold is {value} C",
    )
