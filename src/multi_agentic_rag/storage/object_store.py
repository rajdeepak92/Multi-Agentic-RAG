"""Local object-store adapter for raw files and parsed artifacts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from multi_agentic_rag.models import ChunkRecord, DocumentRecord
from multi_agentic_rag.utils.paths import resolve_path


class LocalObjectStore:
    """Filesystem object store with paths that can later map to MinIO or S3 keys."""

    def __init__(self, root: str | Path, *, raw_documents_dir: str | Path | None = None) -> None:
        self.root = resolve_path(root)
        self.raw_documents_dir = (
            resolve_path(raw_documents_dir) if raw_documents_dir is not None else self.root / "raw"
        )
        self.parsed_dir = self.root / "parsed"

    def initialize(self) -> None:
        """Create object-store directories."""

        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_documents_dir.mkdir(parents=True, exist_ok=True)
        self.parsed_dir.mkdir(parents=True, exist_ok=True)

    def store_source_document(
        self,
        source_path: str | Path,
        *,
        system_name: str,
        version: str,
        content_hash: str,
    ) -> Path:
        """Copy a raw document into the managed object-store raw path."""

        self.initialize()
        source = resolve_path(source_path)
        destination = (
            self.raw_documents_dir
            / f"{system_name}_{version}_{content_hash[:12]}_{source.name}"
        )
        if source != destination:
            shutil.copy2(source, destination)
        return destination

    def store_chunks(self, document: DocumentRecord, chunks: list[ChunkRecord]) -> Path:
        """Persist parsed chunks as JSONL for audit and future re-indexing."""

        self.initialize()
        destination = self.parsed_dir / f"{document.document_id}.chunks.jsonl"
        with destination.open("w", encoding="utf-8") as file_obj:
            for chunk in chunks:
                file_obj.write(json.dumps(chunk.model_dump(mode="json"), sort_keys=True))
                file_obj.write("\n")
        return destination
