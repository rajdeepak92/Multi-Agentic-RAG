"""Chroma vector repository."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import ChunkRecord, RequirementRecord, RetrievalResult
from multi_agentic_rag.exceptions import ConfigError
from multi_agentic_rag.infrastructure.chroma.fingerprint import EmbeddingSpaceFingerprint
from multi_agentic_rag.infrastructure.embeddings import EmbeddingProvider, select_embedding_provider


class ChromaVectorRepository:
    """Persistent ChromaDB adapter with configurable embeddings."""

    def __init__(
        self,
        *,
        path: Path,
        collection_name: str,
        embedding_provider: EmbeddingProvider,
        embedding_fingerprint: EmbeddingSpaceFingerprint | None = None,
        allow_legacy_without_fingerprint: bool = False,
    ) -> None:
        """Initialize the lazy Chroma adapter.

        Args:
            path: Persistent Chroma directory.
            collection_name: Collection that stores knowledge-base chunks.
            embedding_provider: Provider used to embed chunks and queries.
        """

        self.path = path
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider
        self.embedding_fingerprint = embedding_fingerprint
        self.allow_legacy_without_fingerprint = allow_legacy_without_fingerprint
        self._client: Any | None = None
        self._collection: Any | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> ChromaVectorRepository:
        """Build a repository from application settings.

        Args:
            settings: Runtime configuration containing the Chroma path,
                collection name, and embedding provider selection.

        Returns:
            Configured repository instance. The Chroma client is opened lazily on
            first use.
        """

        settings.ensure_project_cache_paths()
        return cls(
            path=settings.chroma_path,
            collection_name=settings.chroma_collection,
            embedding_provider=select_embedding_provider(settings),
            embedding_fingerprint=EmbeddingSpaceFingerprint.from_settings(settings),
            allow_legacy_without_fingerprint=settings.chroma_allow_legacy_without_fingerprint,
        )

    def check_connection(self) -> tuple[bool, str]:
        """Verify Chroma can create or open the collection."""

        try:
            self._get_collection()
        except Exception as exc:
            return False, str(exc)
        return True, "Chroma collection is ready."

    def clear(
        self,
        *,
        system_name: str | None = None,
        kb_name: str | None = None,
    ) -> int:
        """Delete vectors from Chroma.

        Args:
            system_name: Optional system scope. When omitted, the collection is
                deleted and recreated lazily on the next use.
            kb_name: Optional knowledge-base scope within the selected system.

        Returns:
            Number of vector IDs deleted when known.
        """

        collection = self._get_collection()
        if system_name is None:
            count = int(collection.count())
            if self._client is not None:
                self._client.delete_collection(name=self.collection_name)
            self._collection = None
            return count
        filters: dict[str, Any] = {"system_name": system_name}
        if kb_name is not None:
            filters["kb_name"] = kb_name
        raw = collection.get(where=self._build_where(filters))
        ids = list(raw.get("ids", []))
        if ids:
            collection.delete(ids=ids)
        return len(ids)

    def close(self) -> None:
        """Release cached Chroma handles before filesystem cleanup."""

        self._collection = None
        self._client = None

    def index_chunks(self, chunks: list[ChunkRecord]) -> int:
        """Upsert chunks and metadata into Chroma.

        Args:
            chunks: Chunk records from a completed ingestion pass. Each chunk
                contributes text, metadata filters, and one vector embedding.

        Returns:
            Number of chunks upserted into the collection.
        """

        if not chunks:
            return 0
        collection = self._get_collection()
        collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=self.embedding_provider.embed_documents([chunk.text for chunk in chunks]),
            metadatas=[self._metadata(chunk) for chunk in chunks],
        )
        return len(chunks)

    def index_requirements(self, requirements: list[RequirementRecord]) -> int:
        """Upsert canonical requirement vectors without altering source chunks."""

        if not requirements:
            return 0
        collection = self._get_collection()
        ids = [
            requirement.requirement_pk
            or f"requirement:{requirement.document_version_id}:{requirement.requirement_id}"
            for requirement in requirements
        ]
        documents = [requirement.text for requirement in requirements]
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=self.embedding_provider.embed_documents(documents),
            metadatas=[self._requirement_metadata(requirement) for requirement in requirements],
        )
        return len(requirements)

    def query(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str,
        version: str | None = None,
        active_only: bool | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Query chunks by vector similarity.

        Args:
            query_text: User query to embed and search with cosine similarity.
            system_name: System filter applied to Chroma metadata.
            kb_name: Knowledge-base filter applied to Chroma metadata.
            version: Optional source version filter.
            active_only: Whether to restrict results to active chunks. When
                omitted, active evidence is used unless a specific version is
                requested.
            top_k: Maximum number of vector results to return.

        Returns:
            Ranked retrieval results translated from Chroma rows.
        """

        collection = self._get_collection()
        filters: dict[str, Any] = {"system_name": system_name, "kb_name": kb_name}
        if active_only is None:
            active_only = version is None
        if active_only:
            filters["status"] = "active"
        if version:
            filters["version"] = version
        raw = collection.query(
            query_embeddings=[self.embedding_provider.embed_query(query_text)],
            n_results=top_k,
            where=self._build_where(filters),
            include=["documents", "metadatas", "distances"],
        )
        results: list[RetrievalResult] = []
        ids = raw.get("ids", [[]])[0]
        documents = raw.get("documents", [[]])[0]
        metadatas = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]
        for chunk_id, text, metadata, distance in zip(
            ids,
            documents,
            metadatas,
            distances,
            strict=False,
        ):
            score = 1.0 / (1.0 + float(distance or 0.0))
            result_metadata = dict(metadata)
            result_metadata["vector_score"] = score
            result_metadata["vector_distance"] = float(distance or 0.0)
            result_metadata["vector_record_id"] = str(chunk_id)
            source_chunk_id = (
                str(metadata.get("chunk_id") or chunk_id)
                if metadata.get("entity_kind") == "canonical_requirement"
                else str(chunk_id)
            )
            results.append(
                RetrievalResult(
                    chunk_id=source_chunk_id,
                    document_id=str(metadata.get("document_id", "")),
                    document_version_id=str(metadata.get("document_version_id", "")),
                    system_name=str(metadata.get("system_name", "")),
                    kb_name=str(metadata.get("kb_name", "")),
                    version=str(metadata.get("version", "")),
                    source_name=str(metadata.get("source_name", "")),
                    page=int(metadata.get("page", 1)),
                    text=str(text),
                    score=score,
                    sources=["vector"],
                    metadata=result_metadata,
                )
            )
        return results

    def _get_collection(self) -> Any:
        if self._collection is None:
            self.path.mkdir(parents=True, exist_ok=True)
            chromadb = import_module("chromadb")
            self._client = chromadb.PersistentClient(path=str(self.path))
            metadata: dict[str, Any] = {"hnsw:space": "cosine"}
            if self.embedding_fingerprint is not None:
                metadata.update(self.embedding_fingerprint.metadata())
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata=metadata,
            )
            self._validate_collection_fingerprint(self._collection)
        return self._collection

    def _validate_collection_fingerprint(self, collection: Any) -> None:
        if self.embedding_fingerprint is None:
            return
        persisted = EmbeddingSpaceFingerprint.from_metadata(
            getattr(collection, "metadata", None)
        )
        if persisted is None:
            if self.allow_legacy_without_fingerprint:
                return
            raise ConfigError(
                "Chroma collection is missing embedding-space fingerprint metadata. "
                "Create a new collection or explicitly migrate/reindex the collection."
            )
        if not persisted.compatible_with(self.embedding_fingerprint):
            raise ConfigError(
                "Chroma collection embedding-space fingerprint does not match current "
                "embedding settings. Reindex into a versioned collection instead of "
                "mixing vector spaces."
            )

    def _metadata(self, chunk: ChunkRecord) -> dict[str, str | int]:
        return {
            "entity_kind": "source_chunk",
            "document_id": chunk.document_id,
            "document_version_id": chunk.document_version_id,
            "system_name": chunk.system_name,
            "kb_name": chunk.kb_name,
            "version": chunk.version,
            "status": chunk.status.value,
            "source_name": chunk.source_name,
            "page": chunk.page,
            "section_title": chunk.section_title or "",
            "chunk_index": chunk.chunk_index,
            "content_hash": chunk.content_hash,
            "embedding_provider": self.embedding_provider.name,
            "embedding_model": self.embedding_provider.model,
        }

    def _requirement_metadata(self, requirement: RequirementRecord) -> dict[str, str | int | float]:
        return {
            "entity_kind": "canonical_requirement",
            "requirement_pk": requirement.requirement_pk or "",
            "canonical_id": requirement.canonical_id or requirement.requirement_id,
            "requirement_id": requirement.requirement_id,
            "requirement_type": requirement.requirement_type.value,
            "document_id": requirement.document_id,
            "document_version_id": requirement.document_version_id,
            "chunk_id": requirement.chunk_id,
            "system_name": requirement.system_name,
            "kb_name": requirement.kb_name,
            "version": requirement.version,
            "status": requirement.status.value,
            "source_name": requirement.source_name or "",
            "page": requirement.page or 1,
            "section_title": requirement.section_title or "",
            "semantic_key": requirement.semantic_key or "",
            "confidence": requirement.confidence,
            "embedding_provider": self.embedding_provider.name,
            "embedding_model": self.embedding_provider.model,
        }

    @staticmethod
    def _build_where(filters: dict[str, Any]) -> dict[str, Any] | None:
        clean = [{key: value} for key, value in filters.items() if value is not None]
        if not clean:
            return None
        if len(clean) == 1:
            return clean[0]
        return {"$and": clean}
