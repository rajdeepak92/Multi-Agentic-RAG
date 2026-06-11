"""Chunk creation for parsed pages."""

from __future__ import annotations

from multi_agentic_rag.constants import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE
from multi_agentic_rag.ingestion.parser import PageText
from multi_agentic_rag.models import ChunkRecord, DocumentRecord, build_chunk_id
from multi_agentic_rag.utils.hashing import sha256_text


def chunk_pages(
    pages: list[PageText],
    *,
    document: DocumentRecord,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[ChunkRecord]:
    """Split pages into deterministic chunks with stable chunk IDs."""

    splitter = _get_splitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks: list[ChunkRecord] = []
    chunk_index = 0
    for page in pages:
        pieces = splitter(page.text)
        section_title = _infer_section_title(page.text)
        for piece in pieces:
            normalized = piece.strip()
            if not normalized:
                continue
            content_hash = sha256_text(normalized)
            chunks.append(
                ChunkRecord(
                    chunk_id=build_chunk_id(
                        system_name=document.system_name,
                        version=document.version,
                        source_name=document.source_name,
                        page=page.page,
                        chunk_index=chunk_index,
                        content_hash=content_hash,
                    ),
                    document_id=document.document_id,
                    system_name=document.system_name,
                    version=document.version,
                    status=document.status,
                    source_name=document.source_name,
                    page=page.page,
                    section_title=section_title,
                    chunk_index=chunk_index,
                    content_hash=content_hash,
                    text=normalized,
                )
            )
            chunk_index += 1
    return chunks


def _get_splitter(chunk_size: int, chunk_overlap: int):
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        return splitter.split_text
    except Exception:  # pragma: no cover - fallback only
        return lambda text: _simple_split(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def _simple_split(text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - chunk_overlap)
    return chunks


def _infer_section_title(text: str) -> str | None:
    for line in text.splitlines():
        candidate = line.strip()
        if candidate:
            return candidate[:120]
    return None
