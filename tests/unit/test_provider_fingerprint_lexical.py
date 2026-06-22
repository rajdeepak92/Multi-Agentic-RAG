from __future__ import annotations

import asyncio

import pytest

import multi_agentic_rag.llm.gemini_reasoning as gemini_module
from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import RetrievalResult
from multi_agentic_rag.exceptions import ConfigError
from multi_agentic_rag.infrastructure.chroma import EmbeddingSpaceFingerprint
from multi_agentic_rag.infrastructure.chroma.repository import ChromaVectorRepository
from multi_agentic_rag.infrastructure.embeddings import HashEmbeddingProvider
from multi_agentic_rag.llm import build_reasoning_client
from multi_agentic_rag.retrieval.lexical import (
    LexicalSearchQuery,
    PgTextSearchLexicalRepository,
    PostgresNativeFTSLexicalRepository,
)


def test_gemini_provider_requires_api_key() -> None:
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        build_reasoning_client(
            Settings(postgres_dsn="postgresql+asyncpg://x", _env_file=None),
            "gemini",
        )


def test_gemini_provider_reports_missing_optional_dependency(monkeypatch) -> None:
    def missing_import(name: str):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(gemini_module, "import_module", missing_import)

    with pytest.raises(ConfigError, match="optional `gemini` dependency"):
        build_reasoning_client(
            Settings(
                postgres_dsn="postgresql+asyncpg://x",
                gemini_api_key="test-key",
                _env_file=None,
            ),
            "gemini",
        )


def test_embedding_fingerprint_rejects_mismatched_collection(tmp_path) -> None:
    current = EmbeddingSpaceFingerprint.from_settings(
        Settings(postgres_dsn="postgresql+asyncpg://x", _env_file=None)
    )
    other = current.model_copy(update={"model": "different-model"})
    other.hash = other.compute_hash()
    repository = ChromaVectorRepository(
        path=tmp_path,
        collection_name="test",
        embedding_provider=HashEmbeddingProvider(dimensions=8),
        embedding_fingerprint=current,
    )

    with pytest.raises(ConfigError, match="fingerprint does not match"):
        repository._validate_collection_fingerprint(_FakeCollection(other.metadata()))


def test_embedding_fingerprint_accepts_matching_collection(tmp_path) -> None:
    fingerprint = EmbeddingSpaceFingerprint.from_settings(
        Settings(postgres_dsn="postgresql+asyncpg://x", _env_file=None)
    )
    repository = ChromaVectorRepository(
        path=tmp_path,
        collection_name="test",
        embedding_provider=HashEmbeddingProvider(dimensions=8),
        embedding_fingerprint=fingerprint,
    )

    repository._validate_collection_fingerprint(_FakeCollection(fingerprint.metadata()))


def test_embedding_fingerprint_rejects_missing_metadata(tmp_path) -> None:
    fingerprint = EmbeddingSpaceFingerprint.from_settings(
        Settings(postgres_dsn="postgresql+asyncpg://x", _env_file=None)
    )
    repository = ChromaVectorRepository(
        path=tmp_path,
        collection_name="test",
        embedding_provider=HashEmbeddingProvider(dimensions=8),
        embedding_fingerprint=fingerprint,
    )

    with pytest.raises(ConfigError, match="missing embedding-space fingerprint"):
        repository._validate_collection_fingerprint(_FakeCollection({}))


def test_pg_textsearch_lexical_repository_wraps_postgres_search() -> None:
    repo = PgTextSearchLexicalRepository(_FakePostgresRepository("pg_textsearch"))

    ready = asyncio.run(repo.check_readiness())
    results = asyncio.run(
        repo.search(
            LexicalSearchQuery(query_text="temperature", system_name="PROJECT_1", top_k=3)
        )
    )

    assert ready.backend == "pg_textsearch"
    assert ready.ready is True
    assert results[0].sources == ["pg_textsearch"]


def test_native_fts_lexical_repository_is_not_labeled_bm25() -> None:
    repo = PostgresNativeFTSLexicalRepository(_FakePostgresRepository("fts"))

    ready = asyncio.run(repo.check_readiness())
    results = asyncio.run(
        repo.search(
            LexicalSearchQuery(query_text="temperature", system_name="PROJECT_1", top_k=3)
        )
    )

    assert ready.backend == "postgres_fts"
    assert results[0].sources == ["fts"]
    assert "bm25" not in results[0].sources


class _FakeCollection:
    def __init__(self, metadata: dict) -> None:
        self.metadata = metadata


class _FakePostgresRepository:
    def __init__(self, source: str) -> None:
        self.source = source

    async def check_connection(self) -> tuple[bool, str]:
        return True, "ready"

    async def search_chunks(self, query_text: str, **kwargs) -> list[RetrievalResult]:
        return [
            RetrievalResult(
                chunk_id="chunk-1",
                document_id="doc-1",
                document_version_id="dv-1",
                system_name=kwargs["system_name"],
                kb_name=kwargs["kb_name"],
                version="v1",
                source_name="source.md",
                page=1,
                text=query_text,
                score=1.0,
                sources=[self.source],
            )
        ]
