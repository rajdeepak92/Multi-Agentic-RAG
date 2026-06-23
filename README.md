# Multi-Agentic RAG

Portable, CPU-first Enterprise GraphRAG for document ingestion, requirement-ledger discovery, hybrid retrieval, grounded answers, and user-story generation.

The runtime uses PostgreSQL as the authoritative store, Chroma for vectors, and Neo4j for graph projection. Native PostgreSQL full-text search is the default lexical backend. `pg_textsearch` BM25 remains available as an explicit opt-in when the connected PostgreSQL server supports the extension.

## Current Defaults

- Project root: the directory containing `base_config.json` or the repository markers.
- Runtime cache: `.global_cache/`.
- Generated artifacts: `generated/`.
- Lexical backend: `postgres_fts`.
- Embeddings: `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions.
- Chroma collection: `multi_agentic_rag_chunks_minilm_l6_v1`.
- Devices: `auto`, which uses CUDA only when `torch.cuda.is_available()` is true.
- Reasoning: OpenAI by default; use `--model hf` for a local Hugging Face reasoning run.
- Secrets: `.env` only. Keep DSNs, API keys, tokens, and Neo4j passwords out of `base_config.json`.

## Windows CPU Setup

Prerequisites:

- Windows PowerShell.
- Python 3.12 or newer.
- `uv`.
- PostgreSQL reachable through `POSTGRES_DSN`.
- Chroma local persistence, created under `.global_cache`.
- Neo4j reachable through `NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD`.

Bootstrap:

```powershell
.\scripts\bootstrap-windows.ps1
```

Manual equivalent:

```powershell
Copy-Item .env.example .env -ErrorAction SilentlyContinue
Copy-Item base_config.example.json base_config.json -ErrorAction SilentlyContinue
uv sync --dev --extra cpu --link-mode=copy
New-Item -ItemType Directory -Force documents,.global_cache,generated | Out-Null
```

Then edit `.env` with only secrets:

```powershell
POSTGRES_DSN=postgresql+asyncpg://user:password@host:5432/db
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
OPENAI_API_KEY=...
HF_TOKEN=...
```

## Service Checks

```powershell
uv run --no-sync multi-agentic-rag db-check
uv run --no-sync multi-agentic-rag chroma-check
uv run --no-sync multi-agentic-rag graph-check
uv run --no-sync multi-agentic-rag health-check
```

Run migrations:

```powershell
uv run --no-sync alembic upgrade head
```

`db-check` reports PostgreSQL connectivity, configured lexical readiness, and Alembic revision status. With the default `postgres_fts`, the required index is `idx_chunks_text_fts`.

## Optional pg_textsearch

To use BM25 through `pg_textsearch`, opt in explicitly:

```json
{
  "lexical": {
    "backend": "pg_textsearch"
  }
}
```

Then run:

```powershell
uv run --no-sync alembic upgrade head
uv run --no-sync multi-agentic-rag db-check
```

The migration that creates `idx_chunks_text_bm25` is best-effort. Fresh installs no longer fail when a host does not provide `pg_textsearch`; native FTS remains available.

## Ingest

```powershell
uv run --no-sync multi-agentic-rag ingest .\documents\PROJECT_1_BRD_v1.md `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --review
```

`--review` renders deterministic review tables and persists typed review events when supported by PostgreSQL. It does not call a model.

`--review-facts` is separate and opt-in. It asks the configured reasoning provider to review ambiguous extracted facts during ingestion.

Directory ingest:

```powershell
uv run --no-sync multi-agentic-rag ingest-directory .\documents `
  --system PROJECT_1 `
  --version v1 `
  --review
```

## Requirement Ledger

Normal ingestion discovers requirements once and passes a validated `RequirementDiscoveryResult` into persistence. `requirements-rebuild` is the explicit rediscovery command for stored chunks:

```powershell
uv run --no-sync multi-agentic-rag requirements --system PROJECT_1 --version v1
uv run --no-sync multi-agentic-rag requirements-audit --system PROJECT_1 --version v1
uv run --no-sync multi-agentic-rag requirements-rebuild --system PROJECT_1 --version v1
```

Requirement types include `business_rule`, `functional`, `non_functional`, `automation_rule`, `acceptance_criterion`, `definition_of_done`, and `scope_constraint`.

## Ask

```powershell
uv run --no-sync multi-agentic-rag ask "Summarize all requirements and business rules." `
  --system PROJECT_1 `
  --version v1 `
  --review
```

Exhaustive requirement queries enumerate active PostgreSQL ledger records first, then render the full inventory with evidence. Semantic questions use hybrid retrieval across PostgreSQL FTS, Chroma, and Neo4j.

## User Stories

```powershell
uv run --no-sync multi-agentic-rag user-stories `
  --system PROJECT_1 `
  --version v1 `
  --review
```

Combined flow:

```powershell
uv run --no-sync multi-agentic-rag ingest-and-user-stories .\documents\PROJECT_1_BRD_v1.md `
  --system PROJECT_1 `
  --version v1 `
  --review
```

Generated user stories include debug JSON and a trace manifest JSON. Trace manifests record the artifact, workflow/generation context, source document version, requirements, evidence, story ID, config fingerprint, model fingerprint, timestamp, and schema version.

## CPU And GPU Profiles

CPU install:

```powershell
uv sync --dev --extra cpu --link-mode=copy
```

GPU install:

```powershell
uv sync --dev --extra gpu --link-mode=copy
```

HF reasoning dependencies:

```powershell
uv sync --dev --extra hf-reasoning --extra cpu --link-mode=copy
uv run --no-sync multi-agentic-rag hf-check
```

Use local HF reasoning for one command:

```powershell
uv run --no-sync multi-agentic-rag ask "What changed?" `
  --system PROJECT_1 `
  --version v1 `
  --model hf
```

`auto` devices resolve to CPU when CUDA is unavailable. `cuda` fails clearly when CUDA is requested but unavailable.

## Reindexing And Fingerprints

Chroma collections carry embedding-space fingerprints. If you change embedding model, dimension, distance metric, or collection name, do not mix vectors in the existing collection. Use a new versioned collection or reindex intentionally.

The default MiniLM collection is:

```text
multi_agentic_rag_chunks_minilm_l6_v1
```

Source chunks and canonical requirements are stored as separate vector records. Requirement vectors keep source chunk provenance so fusion does not inflate duplicate evidence.

Reindex active PostgreSQL records into the configured Chroma collection without deleting Chroma data:

```powershell
uv run --no-sync multi-agentic-rag chroma-reindex `
  --system PROJECT_1 `
  --version v1
```

## Verification

```powershell
uv lock --check
uv sync --dev --extra cpu --link-mode=copy
uv run --no-sync python -m compileall src tests
uv run --no-sync ruff check .
uv run --no-sync mypy src
uv run --no-sync pytest -q
```

If services are configured:

```powershell
uv run --no-sync alembic upgrade head
uv run --no-sync multi-agentic-rag db-check
uv run --no-sync multi-agentic-rag chroma-check
uv run --no-sync multi-agentic-rag graph-check
uv run --no-sync multi-agentic-rag health-check
```

## References

- Workflow diagram: [work-flow.mermaid](work-flow.mermaid)
- Codebase map: [codebase.md](codebase.md)
