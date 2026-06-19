"""Environment-backed settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimePaths(BaseSettings):
    """Resolved runtime directories.

    Attributes:
        home: Base runtime directory.
        documents: Managed source-document directory.
        objects: Reserved object-storage directory for future derived artifacts.
        manifests: JSONL chunk-manifest directory.
        chroma: Persistent ChromaDB directory.
    """

    home: Path
    documents: Path
    objects: Path
    manifests: Path
    chroma: Path


class Settings(BaseSettings):
    """Runtime settings for the GraphRAG-only platform.

    Values load from process environment and `.env`. The names mirror `.env.example` so
    operators can copy the template and fill in service-specific values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    postgres_dsn: str | None = Field(default=None)

    neo4j_uri: str | None = Field(default="bolt://127.0.0.1:7687")
    neo4j_username: str = Field(default="neo4j")
    neo4j_password: str = Field(default="password")
    neo4j_database: str | None = Field(default="neo4j")
    graphrag_required: bool = Field(default=True)

    chroma_path: Path = Field(default=Path(".multi_agentic_rag/chroma"))
    chroma_collection: str = Field(default="multi_agentic_rag_chunks")

    embedding_provider: Literal["hash", "sentence_transformers"] = Field(
        default="sentence_transformers"
    )
    embedding_model: str = Field(default="BAAI/bge-m3")
    embedding_dimensions: int = Field(default=1024)
    hf_token: str | None = Field(default=None)
    reranker_provider: Literal["none", "sentence_transformers"] = Field(default="none")
    reranker_model: str | None = Field(default=None)

    multi_agentic_rag_home: Path = Field(default=Path(".multi_agentic_rag"))
    object_store_path: Path = Field(default=Path(".multi_agentic_rag/objects"))
    document_store_path: Path = Field(default=Path(".multi_agentic_rag/documents"))
    manifest_store_path: Path = Field(default=Path(".multi_agentic_rag/manifests"))

    chunk_size: int = Field(default=1200)
    chunk_overlap: int = Field(default=160)
    enable_pdf_ocr: bool = Field(default=False)
    tesseract_cmd: str | None = Field(default=None)

    bm25_backend: Literal["postgres"] = Field(default="postgres")
    log_level: str = Field(default="INFO")

    @field_validator("embedding_provider", mode="before")
    @classmethod
    def _normalize_embedding_provider(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() == "huggingface":
            return "sentence_transformers"
        return value

    @field_validator("reranker_provider", mode="before")
    @classmethod
    def _normalize_reranker_provider(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() == "huggingface":
            return "sentence_transformers"
        return value

    def runtime_paths(self) -> RuntimePaths:
        """Create and return runtime directories.

        Returns:
            RuntimePaths with every directory created if it was missing.
        """

        paths = RuntimePaths(
            home=self.multi_agentic_rag_home,
            documents=self.document_store_path,
            objects=self.object_store_path,
            manifests=self.manifest_store_path,
            chroma=self.chroma_path,
        )
        for path in (
            paths.home,
            paths.documents,
            paths.objects,
            paths.manifests,
            paths.chroma,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return paths


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings loaded from the current process environment.

    Returns:
        Cached Settings instance loaded from environment and `.env`.
    """

    return Settings()


def reload_settings() -> Settings:
    """Clear and reload settings.

    Returns:
        Fresh Settings instance after clearing the process cache.
    """

    get_settings.cache_clear()
    return get_settings()
