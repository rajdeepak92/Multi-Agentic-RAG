"""PostgreSQL public adapter layer."""

from multi_agentic_rag.infrastructure.postgres import (
    PostgresKnowledgeRepository,
    create_async_session_factory,
)
from multi_agentic_rag.retrieval.lexical import (
    PgTextSearchLexicalRepository,
    PostgresNativeFTSLexicalRepository,
)

__all__ = [
    "PgTextSearchLexicalRepository",
    "PostgresKnowledgeRepository",
    "PostgresNativeFTSLexicalRepository",
    "create_async_session_factory",
]
