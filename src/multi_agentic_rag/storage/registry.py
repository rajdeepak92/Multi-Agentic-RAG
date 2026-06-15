"""Metadata registry interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from multi_agentic_rag.config import Settings
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

    def search_chunks(
        self,
        query_text: str,
        *,
        system_name: str | None = None,
        version: str | None = None,
        status: DocumentStatus | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]: ...

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


@dataclass(frozen=True)
class RegistrySelection:
    """Selected registry plus provider metadata."""

    provider: str
    registry: Registry
    reason: str


def local_dev_mode_enabled(settings: Settings) -> bool:
    """Return whether local/offline development fallbacks are explicitly allowed."""

    return bool(settings.allow_local_dev_mode)


def require_local_dev_mode(settings: Settings, capability: str) -> None:
    """Reject local fallbacks unless ALLOW_LOCAL_DEV_MODE=true is set."""

    if local_dev_mode_enabled(settings):
        return
    raise RuntimeError(
        f"{capability} requires ALLOW_LOCAL_DEV_MODE=true. Strict mode does not "
        "allow SQLite, Chroma, localhost-only Neo4j fallbacks, or hash embeddings."
    )


def select_registry(settings: Settings) -> RegistrySelection:
    """Select the configured metadata registry."""

    provider = settings.registry_provider.lower()
    if provider == "postgresql":
        if not settings.postgres_dsn:
            raise RuntimeError("REGISTRY_PROVIDER=postgresql requires POSTGRES_DSN.")
        from multi_agentic_rag.storage.postgres_registry import PostgresRegistry

        return RegistrySelection(
            provider="postgresql",
            registry=PostgresRegistry(settings.postgres_dsn),
            reason="PostgreSQL registry selected.",
        )
    if provider == "sqlite":
        require_local_dev_mode(settings, "REGISTRY_PROVIDER=sqlite")
        from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry

        return RegistrySelection(
            provider="sqlite",
            registry=SQLiteRegistry(settings.sqlite_db_path),
            reason="SQLite registry selected for explicit local development.",
        )
    raise ValueError(f"Unsupported registry provider: {settings.registry_provider}")
