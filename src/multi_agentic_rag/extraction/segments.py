"""Source segmentation helpers for ingestion traceability."""

from __future__ import annotations

from multi_agentic_rag.domain import (
    ChunkRecord,
    DocumentVersionRecord,
    PageText,
    SourceSegmentRecord,
)
from multi_agentic_rag.identity import stable_id
from multi_agentic_rag.ingestion import chunk_pages


def segments_from_chunks(chunks: list[ChunkRecord]) -> list[SourceSegmentRecord]:
    """Create deterministic source segments from immutable chunks."""

    segments: list[SourceSegmentRecord] = []
    for index, chunk in enumerate(chunks):
        segment_id = stable_id(
            "segment",
            chunk.document_version_id,
            chunk.chunk_id,
            chunk.content_hash,
        )
        segments.append(
            SourceSegmentRecord(
                segment_id=segment_id,
                document_version_id=chunk.document_version_id,
                document_id=chunk.document_id,
                system_name=chunk.system_name,
                kb_name=chunk.kb_name,
                version=chunk.version,
                status=chunk.status,
                source_name=chunk.source_name,
                page=chunk.page,
                segment_index=index,
                segment_type="chunk",
                section_title=chunk.section_title,
                start_offset=0,
                end_offset=len(chunk.text),
                text=chunk.text,
                chunk_ids=[chunk.chunk_id],
                metadata={"source": "chunk_projection", "chunk_index": chunk.chunk_index},
            )
        )
    return segments


def segments_from_pages(
    pages: list[PageText],
    *,
    document_version: DocumentVersionRecord,
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[list[SourceSegmentRecord], list[ChunkRecord]]:
    """Compatibility helper that chunks pages and then derives segments."""

    chunks = chunk_pages(
        pages,
        document_version=document_version,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return segments_from_chunks(chunks), chunks
