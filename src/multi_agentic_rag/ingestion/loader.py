"""High-level ingestion service."""

from __future__ import annotations

from pathlib import Path
import re

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.delta import compute_fact_deltas
from multi_agentic_rag.exceptions import IngestionError
from multi_agentic_rag.extraction import extract_facts_from_chunk
from multi_agentic_rag.graph.builder import build_basic_graph
from multi_agentic_rag.ingestion.chunker import chunk_pages
from multi_agentic_rag.ingestion.metadata import create_document_record
from multi_agentic_rag.ingestion.parser import load_document_pages
from multi_agentic_rag.models import (
    ChunkRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    FactRecord,
    IngestResult,
)
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore
from multi_agentic_rag.storage.object_store import LocalObjectStore
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.storage.vector_factory import select_vector_store
from multi_agentic_rag.utils.hashing import sha256_file
from multi_agentic_rag.utils.paths import ensure_runtime_dirs, resolve_path


def ingest_document(
    source_path: str | Path,
    *,
    system_name: str,
    version: str,
    settings: Settings | None = None,
) -> IngestResult:
    """Ingest a PDF into the local registry, vector store, and optional Neo4j graph."""

    settings = settings or get_settings()
    runtime_paths = ensure_runtime_dirs(settings)
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()

    source = resolve_path(source_path)
    if not source.exists():
        raise IngestionError(f"Document does not exist: {source}")

    content_hash = sha256_file(source)
    active_documents = registry.list_documents(
        system_name=system_name,
        status=DocumentStatus.ACTIVE,
    )
    active_document = registry.get_active_document(system_name)
    status = DocumentStatus.ACTIVE
    supersedes: str | None = None
    superseded_by: str | None = None
    delta_source_documents: list[DocumentRecord] = []
    if active_document and active_document.version != version:
        if _version_is_newer(version, active_document.version):
            older_active_documents = [
                document
                for document in active_documents
                if _version_is_newer(version, document.version)
            ]
            supersedes = active_document.document_id
            delta_source_documents = older_active_documents or [active_document]
        else:
            status = DocumentStatus.SUPERSEDED
            superseded_by = active_document.document_id
    object_store = LocalObjectStore(
        settings.object_store_path,
        raw_documents_dir=runtime_paths["documents"],
    )
    copied_path = object_store.store_source_document(
        source,
        system_name=system_name,
        version=version,
        content_hash=content_hash,
    )
    document = create_document_record(
        system_name=system_name,
        version=version,
        source_path=copied_path,
        source_name=source.name,
        content_hash=content_hash,
        supersedes=supersedes,
    )
    if status != DocumentStatus.ACTIVE or superseded_by:
        document = document.model_copy(
            update={"status": status, "superseded_by": superseded_by}
        )

    pages = load_document_pages(
        source,
        enable_ocr=settings.enable_pdf_ocr,
        tesseract_cmd=settings.tesseract_cmd,
    )
    chunks = chunk_pages(pages, document=document)
    chunk_manifest_path = object_store.store_chunks(document, chunks)
    facts = _extract_facts(chunks)

    old_facts: list[FactRecord] = []
    deltas: list[DeltaRecord] = []
    if delta_source_documents:
        for delta_source_document in delta_source_documents:
            old_facts.extend(
                registry.list_facts(
                    document_id=delta_source_document.document_id,
                    status=DocumentStatus.ACTIVE,
                )
            )
        deltas = compute_fact_deltas(
            system_name=system_name,
            from_version=delta_source_documents[0].version,
            to_version=version,
            old_facts=old_facts,
            new_facts=facts,
        )

    registry.upsert_document(document)
    registry.upsert_chunks(chunks)
    registry.upsert_facts(facts)
    registry.insert_deltas(deltas)

    superseded_chunks: list[ChunkRecord] = []
    superseded_facts: list[FactRecord] = []
    superseded_documents: list[DocumentRecord] = []
    if delta_source_documents:
        for delta_source_document in delta_source_documents:
            registry.update_document_status(
                delta_source_document.document_id,
                DocumentStatus.SUPERSEDED,
                superseded_by=document.document_id,
            )
            superseded_document = registry.get_document(delta_source_document.document_id)
            if superseded_document:
                superseded_documents.append(superseded_document)
            superseded_chunks.extend(
                registry.list_chunks(document_id=delta_source_document.document_id)
            )
            superseded_facts.extend(
                registry.list_facts(document_id=delta_source_document.document_id)
            )
    if document.status == DocumentStatus.ACTIVE:
        other_active_documents = [
            active
            for active in registry.list_documents(
                system_name=system_name,
                status=DocumentStatus.ACTIVE,
            )
            if active.document_id != document.document_id and active.version != document.version
        ]
        for active in other_active_documents:
            registry.update_document_status(
                active.document_id,
                DocumentStatus.SUPERSEDED,
                superseded_by=document.document_id,
            )
            updated = registry.get_document(active.document_id)
            if updated:
                superseded_documents.append(updated)
                superseded_chunks.extend(registry.list_chunks(document_id=active.document_id))
                superseded_facts.extend(registry.list_facts(document_id=active.document_id))

    warnings: list[str] = []
    vector_provider = _index_vectors(settings, chunks + superseded_chunks, warnings)
    neo4j_available = _build_graph_if_available(
        settings=settings,
        document=document,
        chunks=chunks,
        facts=facts,
        deltas=deltas,
        superseded_documents=superseded_documents,
        superseded_chunks=superseded_chunks,
        superseded_facts=superseded_facts,
        warnings=warnings,
    )

    return IngestResult(
        document=document,
        chunks_indexed=len(chunks),
        facts_extracted=len(facts),
        deltas_created=len(deltas),
        neo4j_available=neo4j_available,
        vector_store=vector_provider,
        keyword_indexed=len(chunks) if settings.keyword_index_enabled else 0,
        object_store_path=str(chunk_manifest_path),
        warnings=warnings,
    )


def _version_is_newer(candidate: str, current: str) -> bool:
    return _version_sort_key(candidate) > _version_sort_key(current)


def _version_sort_key(version: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", version)
    if numbers:
        return tuple(int(number) for number in numbers)
    return tuple(ord(character) for character in version.lower())


def _extract_facts(chunks: list[ChunkRecord]) -> list[FactRecord]:
    facts: list[FactRecord] = []
    for chunk in chunks:
        facts.extend(extract_facts_from_chunk(chunk))
    return facts


def _index_vectors(settings: Settings, chunks: list[ChunkRecord], warnings: list[str]) -> str:
    try:
        selection = select_vector_store(settings)
        selection.store.index_chunks(chunks)
        return selection.provider
    except Exception as exc:  # pragma: no cover - depends on local optional dependency
        warnings.append(f"Vector indexing skipped: {exc}")
        return "unavailable"


def _build_graph_if_available(
    *,
    settings: Settings,
    document: DocumentRecord,
    chunks: list[ChunkRecord],
    facts: list[FactRecord],
    deltas: list[DeltaRecord],
    superseded_documents: list[DocumentRecord],
    superseded_chunks: list[ChunkRecord],
    superseded_facts: list[FactRecord],
    warnings: list[str],
) -> bool:
    graph_store = Neo4jGraphStore(settings)
    available, message = graph_store.check_connection()
    if not available:
        warnings.append(f"Neo4j graph build skipped: {message}")
        return False
    try:
        for superseded_document in superseded_documents:
            build_basic_graph(
                graph_store,
                document=superseded_document,
                chunks=[
                    chunk
                    for chunk in superseded_chunks
                    if chunk.document_id == superseded_document.document_id
                ],
                facts=[
                    fact
                    for fact in superseded_facts
                    if fact.document_id == superseded_document.document_id
                ],
                deltas=[],
            )
        build_basic_graph(
            graph_store,
            document=document,
            chunks=chunks,
            facts=facts,
            deltas=deltas,
        )
    except Exception as exc:  # pragma: no cover - depends on local Neo4j
        warnings.append(f"Neo4j graph build failed: {exc}")
        return False
    finally:
        graph_store.close()
    return True
