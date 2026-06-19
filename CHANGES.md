# Changes

## Breaking Changes

- Removed SQLite metadata storage and SQLite FTS.
- Removed QA automation, coverage planning, generated pytest/Robot artifacts, and execution tracking.
- Removed FastAPI, MCP, LangGraph workflow routing, Weaviate, OpenAI answer synthesis, and local runtime samples.
- Replaced the CLI with exactly `ingest`, `retrieve`, `graph-check`, `db-check`, `chroma-check`, and `health-check`.

## Added

- `KnowledgeBaseStoringAgent` as the top-level ingestion orchestrator.
- PostgreSQL 16+ schema managed by SQLAlchemy 2.x async sessions and Alembic.
- ChromaDB vector indexing with pluggable embeddings.
- Neo4j graph projection with constrained GraphRAG labels and relationships.
- Hybrid retrieval over PostgreSQL FTS, Chroma, and Neo4j with deterministic reciprocal-rank fusion.

## Changed

- Default embeddings now use Hugging Face `BAAI/bge-m3` through `sentence-transformers`; hash embeddings remain available only as deterministic offline fallback.
- Ingestion now fails unless PostgreSQL, ChromaDB, Neo4j projection, chunking, fact extraction, and full Chroma indexing all succeed.

## Verification

```powershell
uv sync --dev
uv run alembic upgrade head
uv run pytest -q
uv run ruff check .
uv run mypy src/multi_agentic_rag
```
