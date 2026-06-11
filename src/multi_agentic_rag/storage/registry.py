"""Metadata registry interface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from multi_agentic_rag.models import (
    ChunkRecord,
    CoverageRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    FactRecord,
)


class Registry(Protocol):
    """Repository interface for deterministic metadata state."""

    db_path: Path

    def initialize(self) -> None: ...

    def upsert_document(self, document: DocumentRecord) -> None: ...

    def get_document(self, document_id: str) -> DocumentRecord | None: ...

    def get_active_document(self, system_name: str) -> DocumentRecord | None: ...

    def list_documents(
        self,
        *,
        system_name: str | None = None,
        status: DocumentStatus | None = None,
    ) -> list[DocumentRecord]: ...

    def update_document_status(
        self,
        document_id: str,
        status: DocumentStatus,
        *,
        superseded_by: str | None = None,
    ) -> None: ...

    def upsert_chunks(self, chunks: list[ChunkRecord]) -> None: ...

    def list_chunks(
        self,
        *,
        system_name: str | None = None,
        version: str | None = None,
        status: DocumentStatus | None = None,
        document_id: str | None = None,
    ) -> list[ChunkRecord]: ...

    def upsert_facts(self, facts: list[FactRecord]) -> None: ...

    def list_facts(
        self,
        *,
        system_name: str | None = None,
        version: str | None = None,
        status: DocumentStatus | None = None,
        document_id: str | None = None,
        fact_key: str | None = None,
    ) -> list[FactRecord]: ...

    def insert_deltas(self, deltas: list[DeltaRecord]) -> None: ...

    def list_deltas(
        self,
        *,
        system_name: str | None = None,
        from_version: str | None = None,
        to_version: str | None = None,
    ) -> list[DeltaRecord]: ...

    def upsert_coverage(self, records: list[CoverageRecord]) -> None: ...

    def list_coverage(
        self,
        *,
        requirement_id: str | None = None,
    ) -> list[CoverageRecord]: ...
