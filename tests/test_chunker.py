from multi_agentic_rag.ingestion.chunker import chunk_pages
from multi_agentic_rag.ingestion.parser import PageText
from multi_agentic_rag.models import DocumentRecord, DocumentStatus, build_chunk_id


def test_chunk_id_stability() -> None:
    first = build_chunk_id(
        system_name="SIIMCS",
        version="v1",
        source_name="brd.pdf",
        page=1,
        chunk_index=0,
        content_hash="abc",
    )
    second = build_chunk_id(
        system_name="SIIMCS",
        version="v1",
        source_name="brd.pdf",
        page=1,
        chunk_index=0,
        content_hash="abc",
    )

    assert first == second


def test_chunk_pages_assigns_stable_metadata() -> None:
    document = DocumentRecord(
        document_id="doc_1",
        system_name="SIIMCS",
        version="v1",
        status=DocumentStatus.ACTIVE,
        source_path="brd.pdf",
        source_name="brd.pdf",
        content_hash="filehash",
    )

    chunks = chunk_pages(
        [PageText(page=1, text="Requirements\nREQ-1 temperature threshold is 80 C.")],
        document=document,
        chunk_size=200,
        chunk_overlap=20,
    )

    assert len(chunks) == 1
    assert chunks[0].document_id == "doc_1"
    assert chunks[0].system_name == "SIIMCS"
    assert chunks[0].status == DocumentStatus.ACTIVE
