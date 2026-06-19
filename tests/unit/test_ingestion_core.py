from __future__ import annotations

import pytest

from multi_agentic_rag.delta import compute_fact_deltas
from multi_agentic_rag.domain import DocumentStatus, DocumentVersionRecord, PageText
from multi_agentic_rag.extraction import extract_facts_from_chunk
from multi_agentic_rag.ingestion import (
    chunk_pages,
    coerce_ingestion_version,
    load_document_pages,
    validate_source_version,
)
from multi_agentic_rag.ingestion.lineage import create_document_records
from multi_agentic_rag.utils.hashing import sha256_text


def _document_version() -> DocumentVersionRecord:
    return DocumentVersionRecord(
        document_version_id="dv1",
        document_id="doc1",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        status=DocumentStatus.ACTIVE,
        source_path="source.md",
        source_name="source_v1.md",
        content_hash="hash",
    )


def test_version_guard_rejects_filename_mismatch(tmp_path) -> None:
    source = tmp_path / "brd_v2.md"
    source.write_text("BRD text", encoding="utf-8")

    with pytest.raises(Exception, match="version v2"):
        validate_source_version(source, "v1")


def test_version_fallback_warns_when_immediate_predecessor_is_missing() -> None:
    effective, warning = coerce_ingestion_version("v2", None)

    assert effective == "v1"
    assert warning is not None
    assert "v1 is not available" in warning

    effective, warning = coerce_ingestion_version("v7", "v5")

    assert effective == "v6"
    assert warning is not None
    assert "current active version is v5" in warning


def test_version_fallback_keeps_next_sequential_version() -> None:
    effective, warning = coerce_ingestion_version("v3", "v2")

    assert effective == "v3"
    assert warning is None


def test_version_fallback_keeps_equal_or_older_version() -> None:
    effective, warning = coerce_ingestion_version("v3", "v3")

    assert effective == "v3"
    assert warning is None

    effective, warning = coerce_ingestion_version("v2", "v3")

    assert effective == "v2"
    assert warning is None


def test_txt_and_markdown_parser(tmp_path) -> None:
    txt = tmp_path / "notes.txt"
    md = tmp_path / "requirements.md"
    txt.write_text("plain text", encoding="utf-8")
    md.write_text("# SRS\nREQ-1 shall use MQTT", encoding="utf-8")

    assert load_document_pages(txt)[0].extraction_method == "text"
    assert load_document_pages(md)[0].extraction_method == "markdown"


def test_chunk_overlap_is_deterministic() -> None:
    page = PageText(page=1, text="abcdef" * 30, extraction_method="text")
    chunks = chunk_pages(
        [page], document_version=_document_version(), chunk_size=50, chunk_overlap=10
    )

    assert len(chunks) > 1
    assert chunks[0].text[-10:] == chunks[1].text[:10]
    assert (
        chunks[0].chunk_id
        == chunk_pages(
            [page],
            document_version=_document_version(),
            chunk_size=50,
            chunk_overlap=10,
        )[0].chunk_id
    )


def test_fact_extraction_excludes_test_case_facts() -> None:
    page = PageText(
        page=1,
        text="REQ-1 temperature threshold maximum is 80 C. TEST-1 is legacy noise.",
        extraction_method="text",
    )
    chunk = chunk_pages(
        [page], document_version=_document_version(), chunk_size=500, chunk_overlap=0
    )[0]

    facts = extract_facts_from_chunk(chunk)

    assert {fact.fact_type for fact in facts} >= {"requirement", "threshold", "sensor"}
    assert "test" not in {fact.fact_type for fact in facts}


def test_delta_includes_added_removed_modified_and_unchanged(tmp_path) -> None:
    source = tmp_path / "brd_v1.md"
    source.write_text("REQ-1 temperature threshold maximum is 80 C.", encoding="utf-8")
    document, old_version = create_document_records(
        source=source,
        managed_source=source,
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        content_hash=sha256_text("old"),
        document_type="brd",
        previous_version_id=None,
    )
    _, new_version = create_document_records(
        source=source,
        managed_source=source,
        system_name="PROJECT_1",
        kb_name="default",
        version="v2",
        content_hash=sha256_text("new"),
        document_type="brd",
        previous_version_id=old_version.document_version_id,
    )
    old_chunks = chunk_pages(
        [
            PageText(
                page=1,
                text="REQ-1 temperature threshold maximum is 80 C. MQTT enabled.",
                extraction_method="text",
            )
        ],
        document_version=old_version,
        chunk_size=500,
        chunk_overlap=0,
    )
    new_chunks = chunk_pages(
        [
            PageText(
                page=1,
                text="REQ-1 temperature threshold maximum is 90 C. REST enabled.",
                extraction_method="text",
            )
        ],
        document_version=new_version,
        chunk_size=500,
        chunk_overlap=0,
    )
    old_facts = [fact for chunk in old_chunks for fact in extract_facts_from_chunk(chunk)]
    new_facts = [fact for chunk in new_chunks for fact in extract_facts_from_chunk(chunk)]

    deltas = compute_fact_deltas(
        system_name=document.system_name,
        kb_name=document.kb_name,
        from_document_version_id=old_version.document_version_id,
        to_document_version_id=new_version.document_version_id,
        from_version="v1",
        to_version="v2",
        old_facts=old_facts,
        new_facts=new_facts,
    )

    change_types = {delta.change_type for delta in deltas}
    assert {"added", "removed", "modified", "unchanged"} <= change_types
