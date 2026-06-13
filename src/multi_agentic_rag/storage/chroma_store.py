"""ChromaDB local persistent vector store."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from multi_agentic_rag.constants import GRAPH_COLLECTION_NAME
from multi_agentic_rag.models import ChunkRecord
from multi_agentic_rag.utils.paths import resolve_path


class HashEmbeddingFunction:
    """Deterministic embedding fallback that avoids model downloads during Phase 1 tests."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def __call__(self, input: Iterable[str]) -> list[list[float]]:  # noqa: A002 - Chroma API name
        return [self._embed(text) for text in input]

    def embed_query(self, input: str | Iterable[str]):  # noqa: A002 - Chroma API name
        """Embed query text for Chroma query paths."""

        if isinstance(input, str):
            return self._embed(input)
        return [self._embed(text) for text in input]

    def embed_documents(self, input: Iterable[str]) -> list[list[float]]:  # noqa: A002
        """Embed document strings for Chroma compatibility."""

        return [self._embed(text) for text in input]

    def is_legacy(self) -> bool:
        """Tell Chroma this embedding function exposes current config hooks."""

        return False

    @staticmethod
    def supported_spaces() -> list[str]:
        """Return vector spaces supported by the deterministic embedding."""

        return ["cosine"]

    @staticmethod
    def default_space() -> str:
        """Return the default Chroma vector space."""

        return "cosine"

    @staticmethod
    def name() -> str:
        """Return the stable Chroma embedding-function name."""

        return "multi_agentic_rag_hash_embedding"

    def get_config(self) -> dict[str, int]:
        """Return serializable Chroma embedding-function configuration."""

        return {"dimensions": self.dimensions}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "HashEmbeddingFunction":
        """Rebuild the embedding function from Chroma collection config."""

        return HashEmbeddingFunction(dimensions=int(config.get("dimensions", 384)))

    def _embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        while len(values) < self.dimensions:
            for byte in digest:
                values.append((byte / 255.0) - 0.5)
                if len(values) == self.dimensions:
                    break
            digest = hashlib.sha256(digest).digest()
        return values


class ChromaVectorStore:
    """Persistent ChromaDB adapter.

    The adapter uses a deterministic local embedding fallback by default. The
    interface is intentionally narrow so a sentence-transformers embedding
    function or an enterprise vector store can replace it later.
    """

    name = "chroma"

    def __init__(
        self,
        path: str | Path,
        *,
        collection_name: str = GRAPH_COLLECTION_NAME,
        embedding_function: Any | None = None,
        embedding_provider: str = "hash",
        embedding_model: str = "multi_agentic_rag_hash_embedding",
    ) -> None:
        self.path = resolve_path(path)
        self.collection_name = collection_name
        self.embedding_function = embedding_function or HashEmbeddingFunction()
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model
        self._client: Any | None = None
        self._collection: Any | None = None

    def _get_collection(self) -> Any:
        if self._collection is None:
            self.path.mkdir(parents=True, exist_ok=True)
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self.path))
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def index_chunks(self, chunks: list[ChunkRecord]) -> None:
        if not chunks:
            return
        collection = self._get_collection()
        collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[self._metadata(chunk) for chunk in chunks],
        )

    def query(
        self,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        collection = self._get_collection()
        where = self._build_where(filters or {})
        results = collection.query(
            query_texts=[query_text],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        return [
            {
                "chunk_id": chunk_id,
                "text": document,
                "metadata": metadata,
                "distance": distance,
            }
            for chunk_id, document, metadata, distance in zip(
                ids,
                documents,
                metadatas,
                distances,
                strict=False,
            )
        ]

    def _metadata(self, chunk: ChunkRecord) -> dict[str, Any]:
        return {
            "document_id": chunk.document_id,
            "system_name": chunk.system_name,
            "version": chunk.version,
            "status": chunk.status.value,
            "source_name": chunk.source_name,
            "page": chunk.page,
            "section_title": chunk.section_title or "",
            "chunk_index": chunk.chunk_index,
            "content_hash": chunk.content_hash,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
        }

    @staticmethod
    def _build_where(filters: dict[str, Any]) -> dict[str, Any] | None:
        clean = [{key: value} for key, value in filters.items() if value is not None]
        if not clean:
            return None
        if len(clean) == 1:
            return clean[0]
        return {"$and": clean}
