"""Knowledge graph store interface."""

from __future__ import annotations

from typing import Protocol

from multi_agentic_rag.models import (
    ChunkRecord,
    CoverageRecord,
    DeltaRecord,
    DocumentRecord,
    FactRecord,
    GeneratedTestFileRecord,
    TestRunResultRecord,
)


class GraphStore(Protocol):
    """Minimal graph database contract."""

    def check_connection(self) -> tuple[bool, str]: ...

    def create_indexes(self) -> None: ...

    def upsert_ingestion_graph(
        self,
        *,
        document: DocumentRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
    ) -> None: ...

    def upsert_generated_test_graph(
        self,
        *,
        test_file: GeneratedTestFileRecord,
        coverage_records: list[CoverageRecord],
    ) -> None: ...

    def upsert_test_run_graph(
        self,
        *,
        result: TestRunResultRecord,
        test_file: GeneratedTestFileRecord | None = None,
    ) -> None: ...
