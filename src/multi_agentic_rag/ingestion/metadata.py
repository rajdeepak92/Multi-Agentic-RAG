"""Metadata construction helpers for ingestion."""

from __future__ import annotations

from pathlib import Path

from multi_agentic_rag.models import DocumentRecord, DocumentStatus
from multi_agentic_rag.utils.hashing import stable_id


def create_document_record(
    *,
    system_name: str,
    version: str,
    source_path: str | Path,
    source_name: str,
    content_hash: str,
    supersedes: str | None = None,
) -> DocumentRecord:
    """Create a stable document record."""

    return DocumentRecord(
        document_id=stable_id("doc", system_name, version, source_name, content_hash),
        system_name=system_name,
        version=version,
        status=DocumentStatus.ACTIVE,
        source_path=str(source_path),
        source_name=source_name,
        content_hash=content_hash,
        supersedes=supersedes,
    )
