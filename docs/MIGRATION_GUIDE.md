# Migration Guide

## Removed

SQLite, Weaviate, FastAPI, MCP, LangGraph workflow routing, QA coverage planning, generated tests, Robot Framework output, generated runtime artifacts, and local Neo4j Desktop state were removed from the production GraphRAG scope.

## PostgreSQL

Create a PostgreSQL 16+ database and set:

```powershell
$env:POSTGRES_DSN="postgresql+asyncpg://marag:marag@127.0.0.1:5432/marag"
uv run alembic upgrade head
```

## End-to-End

```powershell
uv run multi-agentic-rag db-check
uv run multi-agentic-rag chroma-check
uv run multi-agentic-rag graph-check
uv run multi-agentic-rag ingest documents\example_v1.md --system PROJECT_1 --version v1 --kb default
uv run multi-agentic-rag retrieve "requirements for PROJECT_1" --system PROJECT_1
```

Service-dependent integration tests skip when the required DSN or service is unavailable.
