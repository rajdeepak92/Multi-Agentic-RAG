"""Chunk models and stable ID helpers."""

from __future__ import annotations

from pydantic import BaseModel

from multi_agentic_rag.models.document import DocumentStatus
from multi_agentic_rag.utils.hashing import stable_id


def build_chunk_id(
    *,
    system_name: str,
    version: str,
    source_name: str,
    page: int,
    chunk_index: int,
    content_hash: str,
) -> str:
    """Create a deterministic chunk ID from lineage metadata and content hash."""

    return stable_id(
        "chunk",
        system_name,
        version,
        source_name,
        page,
        chunk_index,
        content_hash,
    )


class ChunkRecord(BaseModel):
    """A retrievable text chunk with version and evidence metadata."""

    chunk_id: str
    document_id: str
    system_name: str
    version: str
    status: DocumentStatus
    source_name: str
    page: int
    section_title: str | None = None
    chunk_index: int
    content_hash: str
    text: str
