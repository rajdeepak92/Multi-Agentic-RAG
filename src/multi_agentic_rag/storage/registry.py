"""Metadata registry interface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from multi_agentic_rag.models import (
    ChunkRecord,
    CoverageRecord,
    CoverageRunRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    FactRecord,
    GeneratedTestFileRecord,
    TestRunResultRecord,
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

    def list_coverage_by_ids(self, coverage_ids: list[str]) -> list[CoverageRecord]: ...

    def upsert_coverage_run(self, record: CoverageRunRecord) -> None: ...

    def find_coverage_run(
        self,
        *,
        system_name: str,
        version: str | None,
        scope_hash: str,
        scenario_count: int,
        status: str | None = None,
    ) -> CoverageRunRecord | None: ...

    def upsert_generated_test_file(self, record: GeneratedTestFileRecord) -> None: ...

    def find_generated_test_file(
        self,
        *,
        system_name: str,
        version: str | None,
        scope_hash: str,
    ) -> GeneratedTestFileRecord | None: ...

    def get_generated_test_file(self, test_file_id: str) -> GeneratedTestFileRecord | None: ...

    def insert_test_run_result(self, record: TestRunResultRecord) -> None: ...

    def get_latest_test_result(
        self,
        *,
        system_name: str,
        version: str | None = None,
    ) -> TestRunResultRecord | None: ...
