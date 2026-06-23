"""Typed sub-agents used by the knowledge-base ingestion orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from multi_agentic_rag.config import RuntimePaths, Settings, get_settings
from multi_agentic_rag.delta import compute_fact_deltas
from multi_agentic_rag.domain import (
    ChunkRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    DocumentVersionRecord,
    FactEnrichmentBatch,
    FactEnrichmentSuggestion,
    FactRecord,
    IngestionRunRecord,
    IngestionRunStatus,
    PageText,
    RequirementEvidenceRecord,
    RequirementRecord,
    SystemRecord,
)
from multi_agentic_rag.exceptions import IngestionError
from multi_agentic_rag.extraction import extract_facts_from_chunk
from multi_agentic_rag.ingestion import (
    chunk_pages,
    coerce_ingestion_version,
    create_document_records,
    infer_document_type,
    load_document_pages,
    validate_source_version,
    version_is_newer,
)
from multi_agentic_rag.ingestion.lineage import copy_managed_source
from multi_agentic_rag.ingestion.manifest import write_chunk_manifest
from multi_agentic_rag.utils.hashing import sha256_file, stable_id


class KnowledgeRepository(Protocol):
    """Persistence methods required by ingestion."""

    async def check_connection(self) -> tuple[bool, str]:
        """Check PostgreSQL and FTS readiness.

        Returns:
            Tuple of readiness flag and human-readable detail.
        """

    async def begin_ingestion_run(self, run: IngestionRunRecord) -> None:
        """Create a started run row.

        Args:
            run: Ingestion run record with status `started` and source metadata.
        """

    async def mark_run_succeeded(
        self,
        ingestion_run_id: str,
        *,
        document_id: str,
        document_version_id: str,
    ) -> None:
        """Mark a run succeeded.

        Args:
            ingestion_run_id: Stable run identifier created before parsing.
            document_id: Persisted source document identifier.
            document_version_id: Persisted version identifier for this ingest.
        """

    async def mark_run_stage(
        self,
        ingestion_run_id: str,
        status: IngestionRunStatus,
    ) -> None:
        """Mark a run stage checkpoint.

        Args:
            ingestion_run_id: Stable run identifier to update.
            status: Stage state reached by the ingest pipeline.
        """

    async def mark_run_failed(self, ingestion_run_id: str, error_message: str) -> None:
        """Mark a run failed.

        Args:
            ingestion_run_id: Stable run identifier to update.
            error_message: Classified or raw failure detail to store.
        """

    async def get_active_document_version(
        self,
        *,
        system_name: str,
        kb_name: str,
    ) -> DocumentVersionRecord | None:
        """Return the active version.

        Args:
            system_name: System whose active version should be loaded.
            kb_name: Knowledge-base context within the system.

        Returns:
            Active document version, or `None` when no version exists.
        """

    async def list_facts_for_version(self, document_version_id: str) -> list[FactRecord]:
        """Return facts for a version.

        Args:
            document_version_id: Version identifier whose extracted facts should be loaded.

        Returns:
            Facts attached to the requested version.
        """

    async def list_chunks_for_version(self, document_version_id: str) -> list[ChunkRecord]:
        """Return chunks for a version.

        Args:
            document_version_id: Version identifier whose chunks should be loaded.

        Returns:
            Chunks attached to the requested version.
        """

    async def persist_ingestion(
        self,
        *,
        system: SystemRecord,
        document: DocumentRecord,
        document_version: DocumentVersionRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
        superseded_version_id: str | None,
    ) -> None:
        """Persist an ingestion bundle.

        Args:
            system: System row to upsert.
            document: Stable source document row to upsert.
            document_version: Specific version row to upsert.
            chunks: Text chunks derived from parsed pages.
            facts: Extracted facts tied to chunks.
            deltas: Version deltas to store for newer ingests.
            superseded_version_id: Previous active version to mark superseded, if any.
        """


class VectorRepository(Protocol):
    """Vector repository methods required by ingestion."""

    def check_connection(self) -> tuple[bool, str]:
        """Check vector store readiness.

        Returns:
            Tuple of readiness flag and detail message.
        """

    def index_chunks(self, chunks: list[ChunkRecord]) -> int:
        """Index chunks.

        Args:
            chunks: Chunks to embed and upsert into the vector store.

        Returns:
            Number of chunks indexed.
        """


class GraphRepository(Protocol):
    """Graph repository methods required by ingestion."""

    def check_connection(self) -> tuple[bool, str]:
        """Check graph readiness.

        Returns:
            Tuple of readiness flag and detail message.
        """

    def upsert_graph(
        self,
        *,
        document: DocumentRecord,
        document_version: DocumentVersionRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
        requirements: list[RequirementRecord] | None = None,
        requirement_evidence: list[RequirementEvidenceRecord] | None = None,
    ) -> None:
        """Project graph state.

        Args:
            document: Stable document metadata.
            document_version: Version metadata for this ingest.
            chunks: Chunks to project as graph nodes.
            facts: Facts to project and connect to chunks/requirements/entities.
            deltas: Deltas to project between versions.
        """


class SettingsBootstrapAgent:
    """Load settings."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Create a settings loader.

        Args:
            settings: Optional prebuilt settings object used instead of environment loading.
        """

        self._settings = settings

    def load(self) -> Settings:
        """Return settings.

        Returns:
            The injected settings object or freshly loaded environment settings.
        """

        return self._settings or get_settings()


class RuntimeDirectoryAgent:
    """Create runtime directories."""

    def ensure(self, settings: Settings) -> RuntimePaths:
        """Create and return runtime paths.

        Args:
            settings: Runtime settings containing directory paths.

        Returns:
            Resolved runtime paths after creating missing directories.
        """

        return settings.runtime_paths()


class DocumentResolutionAgent:
    """Resolve source paths."""

    def resolve(self, document_input: str | Path) -> Path:
        """Resolve and validate an input path.

        Args:
            document_input: Source path supplied by CLI or caller.

        Returns:
            Absolute source file path.

        Raises:
            IngestionError: If the path does not exist or is not a file.
        """

        source = Path(document_input).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise IngestionError(f"Document does not exist: {source}")
        return source


class DocumentVersioningAgent:
    """Validate and compare source versions."""

    def validate(self, source: Path, version: str) -> None:
        """Validate filename version hints.

        Args:
            source: Source document path.
            version: Caller-supplied version label.

        Raises:
            IngestionError: If the filename suggests a different version.
        """

        validate_source_version(source, version)

    def is_newer(self, candidate: str, current: str) -> bool:
        """Return whether candidate is newer than current.

        Args:
            candidate: Proposed new version label.
            current: Currently active version label.

        Returns:
            `True` when `candidate` sorts after `current`.
        """

        return version_is_newer(candidate, current)

    def coerce(
        self,
        requested_version: str,
        previous_version: DocumentVersionRecord | None,
    ) -> tuple[str, str | None]:
        """Return the effective version and warning for missing predecessor versions.

        Args:
            requested_version: User-supplied version label.
            previous_version: Active version record currently stored in PostgreSQL.

        Returns:
            Effective version label plus optional warning.
        """

        return coerce_ingestion_version(
            requested_version,
            previous_version.version if previous_version else None,
        )


class HashingAgent:
    """Hash source files."""

    def hash_source(self, source: Path) -> str:
        """Hash a file.

        Args:
            source: File path to hash.

        Returns:
            SHA-256 hex digest of the file content.
        """

        return sha256_file(source)


class SourceStorageAgent:
    """Copy managed source files."""

    def store(
        self,
        source: Path,
        *,
        runtime_paths: RuntimePaths,
        system_name: str,
        kb_name: str,
        version: str,
        content_hash: str,
    ) -> Path:
        """Copy source into managed storage.

        Args:
            source: Source file to copy.
            runtime_paths: Runtime directory collection.
            system_name: System namespace for the managed path.
            kb_name: Knowledge-base namespace for the managed path.
            version: Version label for the managed path.
            content_hash: SHA-256 digest used in the managed filename.

        Returns:
            Path to the copied managed source file.
        """

        return copy_managed_source(
            source,
            documents_dir=runtime_paths.documents,
            system_name=system_name,
            kb_name=kb_name,
            version=version,
            content_hash=content_hash,
        )


class MetadataAgent:
    """Infer document metadata and construct records."""

    def infer_type(self, source: Path, pages: list[PageText]) -> str:
        """Infer SRS/BRD/source type metadata.

        Args:
            source: Source document path.
            pages: Parsed page records used as content evidence.

        Returns:
            Document type label such as `brd`, `srs`, `pdf`, `docx`, or `document`.
        """

        sample_text = "\n".join(page.text for page in pages[:2])
        return infer_document_type(source, sample_text)

    def create_records(
        self,
        *,
        source: Path,
        managed_source: Path,
        system_name: str,
        kb_name: str,
        version: str,
        content_hash: str,
        document_type: str,
        previous_version_id: str | None,
        status: DocumentStatus,
    ) -> tuple[DocumentRecord, DocumentVersionRecord]:
        """Create deterministic document records.

        Args:
            source: Original source path.
            managed_source: Copied source path under runtime storage.
            system_name: Owning system name.
            kb_name: Knowledge-base name.
            version: Version label for the new record.
            content_hash: SHA-256 digest of source content.
            document_type: Inferred document type metadata.
            previous_version_id: Version ID superseded by this ingest, when applicable.
            status: Lifecycle status for the new version.

        Returns:
            Stable document record and version-specific record.
        """

        document, document_version = create_document_records(
            source=source,
            managed_source=managed_source,
            system_name=system_name,
            kb_name=kb_name,
            version=version,
            content_hash=content_hash,
            document_type=document_type,
            previous_version_id=previous_version_id,
        )
        if status != document_version.status:
            document_version = document_version.model_copy(update={"status": status})
        return document, document_version


class ParserAgent:
    """Parse source documents."""

    def parse(self, source: Path, settings: Settings) -> list[PageText]:
        """Parse source pages.

        Args:
            source: Source document path.
            settings: Runtime settings controlling OCR and parser options.

        Returns:
            Parsed logical pages with extraction method metadata.
        """

        return load_document_pages(
            source,
            enable_ocr=settings.enable_pdf_ocr,
            tesseract_cmd=settings.tesseract_cmd,
        )


class ChunkingAgent:
    """Chunk parsed pages."""

    def chunk(
        self,
        pages: list[PageText],
        *,
        document_version: DocumentVersionRecord,
        settings: Settings,
    ) -> list[ChunkRecord]:
        """Create chunks.

        Args:
            pages: Parsed page records.
            document_version: Version metadata attached to every chunk.
            settings: Runtime settings containing chunk size and overlap.

        Returns:
            Deterministic chunk records.
        """

        return chunk_pages(
            pages,
            document_version=document_version,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )


class ManifestAgent:
    """Persist chunk manifests."""

    def write(
        self,
        *,
        runtime_paths: RuntimePaths,
        document_version: DocumentVersionRecord,
        chunks: list[ChunkRecord],
    ) -> Path:
        """Write a chunk manifest.

        Args:
            runtime_paths: Runtime directory collection.
            document_version: Version metadata used in the manifest path.
            chunks: Chunks to serialize as JSONL.

        Returns:
            Path to the manifest file.
        """

        return write_chunk_manifest(
            manifests_dir=runtime_paths.manifests,
            document_version=document_version,
            chunks=chunks,
        )


class FactExtractionAgent:
    """Extract deterministic facts."""

    def extract(self, chunks: list[ChunkRecord]) -> list[FactRecord]:
        """Extract facts from chunks.

        Args:
            chunks: Chunks whose text should be scanned by deterministic extractors.

        Returns:
            Extracted facts with source lineage attached.
        """

        facts: list[FactRecord] = []
        for chunk in chunks:
            facts.extend(extract_facts_from_chunk(chunk))
        return facts


class FactReviewClient(Protocol):
    """Fact review contract used for ingest-time LLM enrichment."""

    async def review_facts(
        self,
        *,
        chunk_text: str,
        facts: list[dict[str, Any]],
    ) -> FactEnrichmentBatch:
        """Review ambiguous facts extracted from a single chunk."""


class FactEnrichmentAgent:
    """LLM-assisted validation and enrichment for ambiguous facts."""

    def __init__(self, reviewer: FactReviewClient | None = None) -> None:
        self.reviewer = reviewer

    async def enrich(
        self,
        *,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
    ) -> list[FactRecord]:
        """Annotate ambiguous facts without changing the canonical fact set."""

        if not self.reviewer:
            return facts
        by_chunk: dict[str, list[FactRecord]] = {}
        for fact in facts:
            by_chunk.setdefault(fact.chunk_id, []).append(fact)
        enriched: list[FactRecord] = []
        for chunk in chunks:
            chunk_facts = by_chunk.get(chunk.chunk_id, [])
            candidates = [fact for fact in chunk_facts if _needs_review(fact, chunk.text)]
            if not candidates:
                enriched.extend(chunk_facts)
                continue
            try:
                review = await self.reviewer.review_facts(
                    chunk_text=chunk.text,
                    facts=[_review_payload(fact) for fact in candidates],
                )
            except Exception:  # pragma: no cover - best-effort sidecar
                enriched.extend(chunk_facts)
                continue
            suggestion_by_fact_id = {
                suggestion.fact_id: suggestion for suggestion in review.suggestions
            }
            for fact in chunk_facts:
                suggestion = suggestion_by_fact_id.get(fact.fact_id)
                enriched.append(_merge_fact_review(fact, suggestion) if suggestion else fact)
        return enriched


class DeltaAnalysisAgent:
    """Compute fact-level deltas."""

    def compute(
        self,
        *,
        system_name: str,
        kb_name: str,
        previous_version: DocumentVersionRecord,
        document_version: DocumentVersionRecord,
        old_facts: list[FactRecord],
        new_facts: list[FactRecord],
    ) -> list[DeltaRecord]:
        """Compute deltas.

        Args:
            system_name: Owning system name.
            kb_name: Knowledge-base context.
            previous_version: Prior active version metadata.
            document_version: New version metadata.
            old_facts: Facts from the prior active version.
            new_facts: Facts extracted from the new version.

        Returns:
            Added, removed, modified, and unchanged fact deltas.
        """

        return compute_fact_deltas(
            system_name=system_name,
            kb_name=kb_name,
            from_document_version_id=previous_version.document_version_id,
            to_document_version_id=document_version.document_version_id,
            from_version=previous_version.version,
            to_version=document_version.version,
            old_facts=old_facts,
            new_facts=new_facts,
        )


class PostgresPersistenceAgent:
    """PostgreSQL persistence sub-agent."""

    def __init__(self, repository: KnowledgeRepository) -> None:
        """Create a persistence sub-agent.

        Args:
            repository: Repository implementing PostgreSQL-backed ingestion methods.
        """

        self.repository = repository

    async def begin_run(self, run: IngestionRunRecord) -> None:
        """Create a started run row.

        Args:
            run: Ingestion run record to insert or update.
        """

        await self.repository.begin_ingestion_run(run)

    async def fail_run(self, ingestion_run_id: str, error_message: str) -> None:
        """Mark a run failed.

        Args:
            ingestion_run_id: Run identifier to update.
            error_message: Failure detail to store.
        """

        await self.repository.mark_run_failed(ingestion_run_id, error_message)

    async def mark_stage(
        self,
        ingestion_run_id: str,
        status: IngestionRunStatus,
    ) -> None:
        """Mark a stage checkpoint for an ingestion run."""

        await self.repository.mark_run_stage(ingestion_run_id, status)

    async def succeed_run(
        self,
        ingestion_run_id: str,
        *,
        document_id: str,
        document_version_id: str,
    ) -> None:
        """Mark a run succeeded.

        Args:
            ingestion_run_id: Run identifier to update.
            document_id: Persisted document identifier.
            document_version_id: Persisted version identifier.
        """

        await self.repository.mark_run_succeeded(
            ingestion_run_id,
            document_id=document_id,
            document_version_id=document_version_id,
        )

    async def active_version(
        self, *, system_name: str, kb_name: str
    ) -> DocumentVersionRecord | None:
        """Return the active version.

        Args:
            system_name: Owning system name.
            kb_name: Knowledge-base context.

        Returns:
            Active version record, or `None` if no active version exists.
        """

        return await self.repository.get_active_document_version(
            system_name=system_name,
            kb_name=kb_name,
        )

    async def facts_for_version(self, document_version_id: str) -> list[FactRecord]:
        """Return facts for a version.

        Args:
            document_version_id: Version identifier to load.

        Returns:
            Facts stored for that version.
        """

        return await self.repository.list_facts_for_version(document_version_id)

    async def chunks_for_version(self, document_version_id: str) -> list[ChunkRecord]:
        """Return chunks for a version.

        Args:
            document_version_id: Version identifier to load.

        Returns:
            Chunks stored for that version.
        """

        return await self.repository.list_chunks_for_version(document_version_id)

    async def persist(
        self,
        *,
        system: SystemRecord,
        document: DocumentRecord,
        document_version: DocumentVersionRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
        superseded_version_id: str | None,
    ) -> None:
        """Persist an ingestion bundle.

        Args:
            system: System record.
            document: Stable document record.
            document_version: New document version record.
            chunks: Chunks to persist.
            facts: Extracted facts to persist.
            deltas: Version deltas to persist.
            superseded_version_id: Previous active version ID to supersede, when present.
        """

        await self.repository.persist_ingestion(
            system=system,
            document=document,
            document_version=document_version,
            chunks=chunks,
            facts=facts,
            deltas=deltas,
            superseded_version_id=superseded_version_id,
        )

    async def check_bm25(self) -> tuple[bool, str]:
        """Check PostgreSQL lexical-search readiness.

        Returns:
            Tuple of readiness flag and detail message.
        """

        return await self.repository.check_connection()


class ChromaIndexingAgent:
    """Chroma indexing sub-agent."""

    def __init__(self, repository: VectorRepository) -> None:
        """Create a Chroma indexing sub-agent.

        Args:
            repository: Vector repository used for indexing and readiness checks.
        """

        self.repository = repository

    def index(self, chunks: list[ChunkRecord]) -> int:
        """Index chunks.

        Args:
            chunks: Chunks to embed and upsert.

        Returns:
            Number of chunks indexed.
        """

        return self.repository.index_chunks(chunks)

    def check(self) -> tuple[bool, str]:
        """Check Chroma readiness.

        Returns:
            Tuple of readiness flag and detail message.
        """

        return self.repository.check_connection()


class Neo4jGraphAgent:
    """Neo4j graph projection sub-agent."""

    def __init__(self, repository: GraphRepository) -> None:
        """Create a graph projection sub-agent.

        Args:
            repository: Graph repository used for readiness checks and projection.
        """

        self.repository = repository

    def project(
        self,
        *,
        document: DocumentRecord,
        document_version: DocumentVersionRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
        requirements: list[RequirementRecord] | None = None,
        requirement_evidence: list[RequirementEvidenceRecord] | None = None,
    ) -> None:
        """Project graph records.

        Args:
            document: Stable document record.
            document_version: Version record for this ingest.
            chunks: Chunk nodes to project.
            facts: Fact nodes and requirement/entity links to project.
            deltas: Delta nodes and version links to project.
            requirements: Canonical ledger requirements to project.
            requirement_evidence: One-to-many evidence spans for requirements.
        """

        self.repository.upsert_graph(
            document=document,
            document_version=document_version,
            chunks=chunks,
            facts=facts,
            deltas=deltas,
            requirements=requirements or [],
            requirement_evidence=requirement_evidence or [],
        )

    def check(self) -> tuple[bool, str]:
        """Check graph readiness.

        Returns:
            Tuple of readiness flag and detail message.
        """

        return self.repository.check_connection()


class ValidationAgent:
    """Final deterministic validation."""

    def validate(self, *, chunks: list[ChunkRecord], facts: list[FactRecord]) -> None:
        """Validate minimum retained ingestion outputs.

        Args:
            chunks: Chunks produced by the current ingest.
            facts: Facts extracted from those chunks.

        Raises:
            IngestionError: If no chunks exist or a fact references a missing chunk.
        """

        if not chunks:
            raise IngestionError("No chunks were created from the document.")
        if not facts:
            raise IngestionError(
                "No facts were extracted from the document. Ingestion requires at least one "
                "requirement, threshold, protocol, device, sensor, or topic fact."
            )
        chunk_ids = {chunk.chunk_id for chunk in chunks}
        dangling = [fact.fact_id for fact in facts if fact.chunk_id not in chunk_ids]
        if dangling:
            raise IngestionError(f"Extracted facts reference missing chunks: {dangling[:3]}")


def _needs_review(fact: FactRecord, chunk_text: str) -> bool:
    if fact.fact_type in {"requirement", "sensor", "protocol"}:
        return False
    evidence = f"{fact.evidence} {chunk_text}".lower()
    ambiguous_markers = (" and ", " or ", "/", ";", ", and ", " together with ", " plus ")
    return any(marker in evidence for marker in ambiguous_markers) or fact.fact_type in {
        "device",
        "protocol_detail",
        "topic",
        "threshold",
    }


def _review_payload(fact: FactRecord) -> dict[str, object]:
    return {
        "fact_id": fact.fact_id,
        "fact_key": fact.fact_key,
        "fact_type": fact.fact_type,
        "value": fact.value,
        "evidence": fact.evidence,
        "unit": fact.unit,
        "requirement_id": fact.requirement_id,
        "semantic_key": fact.semantic_key,
        "metadata": fact.metadata,
    }


def _merge_fact_review(
    fact: FactRecord,
    suggestion: FactEnrichmentSuggestion | None,
) -> FactRecord:
    if suggestion is None:
        return fact
    metadata = dict(fact.metadata)
    metadata.update(
        {
            "llm_reviewed": True,
            "llm_review_status": suggestion.review_status,
            "llm_review_confidence": suggestion.confidence,
            "llm_review_reasoning": suggestion.reasoning_summary,
            "llm_uncertain_relationships": suggestion.uncertain_relationships,
            "llm_split_candidates": [
                candidate.model_dump(mode="json")
                for candidate in suggestion.split_candidates
            ],
        }
    )
    if suggestion.canonical_name:
        metadata["llm_canonical_name"] = suggestion.canonical_name
    if suggestion.relationship_hint:
        metadata["llm_relationship_hint"] = suggestion.relationship_hint
    return fact.model_copy(update={"metadata": metadata})


def build_system_record(system_name: str) -> SystemRecord:
    """Build a deterministic system record.

    Args:
        system_name: Human-readable system name used as the stable identity seed.

    Returns:
        System record with a stable ID.
    """

    return SystemRecord(system_id=stable_id("system", system_name), system_name=system_name)
