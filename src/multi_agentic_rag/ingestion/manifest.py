"""Chunk manifest writer."""

from __future__ import annotations

from pathlib import Path

from multi_agentic_rag.domain import ChunkRecord, DocumentVersionRecord


def write_chunk_manifest(
    *,
    manifests_dir: Path,
    document_version: DocumentVersionRecord,
    chunks: list[ChunkRecord],
) -> Path:
    """Write a JSONL chunk manifest and return its path.

    Args:
        manifests_dir: Root directory for chunk manifests.
        document_version: Version metadata used to name and group the manifest.
        chunks: Chunk records to serialize, one JSON object per line.

    Returns:
        Path to the written manifest file.
    """

    target_dir = manifests_dir / document_version.system_name / document_version.kb_name
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{document_version.document_version_id}.jsonl"
    with path.open("w", encoding="utf-8") as file_obj:
        for chunk in chunks:
            file_obj.write(chunk.model_dump_json() + "\n")
    return path
