"""Explicit lexical-search repository abstractions."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import RetrievalResult
from multi_agentic_rag.exceptions import ConfigError
from multi_agentic_rag.infrastructure.postgres import PostgresKnowledgeRepository


class ReadinessResult(BaseModel):
    """Readiness status for a lexical backend."""

    ready: bool
    backend: str
    detail: str


class LexicalSearchQuery(BaseModel):
    """Structured lexical query."""

    query_text: str
    system_name: str
    kb_name: str = "default"
    version: str | None = None
    active_only: bool | None = None
    top_k: int = 5


class LexicalSearchRepository(Protocol):
    """Repository contract for lexical retrieval."""

    async def check_readiness(self) -> ReadinessResult:
        """Check backend readiness."""

    async def search(self, query: LexicalSearchQuery) -> list[RetrievalResult]:
        """Run lexical retrieval."""

    async def search_chunks(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str,
        version: str | None = None,
        active_only: bool | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Compatibility method used by lexical retrievers."""


class _PostgresLexicalRepository:
    backend: str

    def __init__(self, repository: PostgresKnowledgeRepository) -> None:
        self.repository = repository

    async def check_readiness(self) -> ReadinessResult:
        ready, detail = await self.repository.check_connection()
        return ReadinessResult(ready=ready, backend=self.backend, detail=detail)

    async def search(self, query: LexicalSearchQuery) -> list[RetrievalResult]:
        return await self.repository.search_chunks(
            query.query_text,
            system_name=query.system_name,
            kb_name=query.kb_name,
            version=query.version,
            active_only=query.active_only,
            top_k=query.top_k,
        )

    async def search_chunks(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str,
        version: str | None = None,
        active_only: bool | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Compatibility method used by BM25Retriever."""

        return await self.search(
            LexicalSearchQuery(
                query_text=query_text,
                system_name=system_name,
                kb_name=kb_name,
                version=version,
                active_only=active_only,
                top_k=top_k,
            )
        )


class PgTextSearchLexicalRepository(_PostgresLexicalRepository):
    """PostgreSQL pg_textsearch BM25 repository."""

    backend = "pg_textsearch"


class PostgresNativeFTSLexicalRepository(_PostgresLexicalRepository):
    """Native PostgreSQL FTS repository. This is not BM25."""

    backend = "postgres_fts"


def build_lexical_repository(settings: Settings) -> LexicalSearchRepository:
    """Build the configured lexical repository."""

    postgres = PostgresKnowledgeRepository.from_settings(settings)
    if settings.bm25_backend == "pg_textsearch":
        return PgTextSearchLexicalRepository(postgres)
    if settings.bm25_backend == "postgres_fts":
        return PostgresNativeFTSLexicalRepository(postgres)
    raise ConfigError(f"Unsupported lexical backend: {settings.bm25_backend}")
