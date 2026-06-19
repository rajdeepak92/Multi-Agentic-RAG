"""Deterministic chunk creation for parsed pages."""

from __future__ import annotations

from multi_agentic_rag.domain import ChunkRecord, DocumentVersionRecord, PageText, build_chunk_id
from multi_agentic_rag.utils.hashing import sha256_text


def chunk_pages(
    pages: list[PageText],
    *,
    document_version: DocumentVersionRecord,
    chunk_size: int,
    chunk_overlap: int,
) -> list[ChunkRecord]:
    """Split pages into deterministic chunks with stable IDs.

    Args:
        pages: Parsed page records to split.
        document_version: Version metadata attached to every emitted chunk.
        chunk_size: Maximum target character count per chunk.
        chunk_overlap: Character overlap preserved between adjacent chunks.

    Returns:
        Chunk records with stable IDs, content hashes, and source lineage.

    Raises:
        ValueError: If chunk settings are invalid.
    """

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size.")
    chunks: list[ChunkRecord] = []
    chunk_index = 0
    for page in pages:
        for piece in _split_text(page.text, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
            normalized = piece.strip()
            if not normalized:
                continue
            content_hash = sha256_text(normalized)
            chunks.append(
                ChunkRecord(
                    chunk_id=build_chunk_id(
                        system_name=document_version.system_name,
                        version=document_version.version,
                        source_name=document_version.source_name,
                        page=page.page,
                        chunk_index=chunk_index,
                        content_hash=content_hash,
                    ),
                    document_version_id=document_version.document_version_id,
                    document_id=document_version.document_id,
                    system_name=document_version.system_name,
                    kb_name=document_version.kb_name,
                    version=document_version.version,
                    status=document_version.status,
                    source_name=document_version.source_name,
                    page=page.page,
                    section_title=_infer_section_title(page.text),
                    chunk_index=chunk_index,
                    content_hash=content_hash,
                    text=normalized,
                    metadata={"extraction_method": page.extraction_method},
                )
            )
            chunk_index += 1
    return chunks


def _split_text(text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        window = text[start:end]
        if end < len(text):
            boundary = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "))
            minimum = int(chunk_size * 0.5)
            if boundary >= minimum:
                end = start + boundary + 1
                window = text[start:end]
        chunks.append(window)
        if end >= len(text):
            break
        start = max(0, end - chunk_overlap)
    return chunks


def _infer_section_title(text: str) -> str | None:
    for line in text.splitlines():
        candidate = line.strip(" #\t")
        if candidate:
            return candidate[:120]
    return None
