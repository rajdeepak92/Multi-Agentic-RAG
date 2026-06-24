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
- Reasoning: Azure OpenAI in the enterprise profile; use `--model hf` for local Hugging Face dry runs.
- Secrets: `.env` only. Keep DSNs, API keys, tokens, and Neo4j passwords out of `base_config.json`.

## Configuration Profiles

The repository now supports two explicit reasoning paths:

- Azure OpenAI for production-like runs with deployment routing, strict structured output, and token accounting.
- Hugging Face for local dry runs and offline validation where token usage may be unavailable or zero.

### Azure OpenAI

Use Azure when you want the enterprise model routing:

```dotenv
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_KEY=<your_azure_openai_api_key>
AZURE_OPENAI_API_VERSION=<your_azure_openai_api_version>
```

Azure deployment names come from `base_config.json` or the matching environment-backed settings:

- `gpt-5.2-chat` for final user-story generation, Ask synthesis, and story-group analysis.
- `gpt-4o-mini` for query planning, semantic review, validation, reranking, and fact review.
- `text-embedding-3-large` for production embeddings.

Before enabling Azure in a run, validate the endpoint and deployment routing:

```powershell
uv run --no-sync multi-agentic-rag azure-check
uv run --no-sync multi-agentic-rag embedding-check
uv run --no-sync multi-agentic-rag reranker-check
```

### Hugging Face Dry Runs

Use Hugging Face when you need local, offline, or private-model dry runs:

```dotenv
HF_TOKEN=<your_huggingface_token>
HF_REASON_MODEL=<your_private_or_local_reasoning_model>
HF_REASON_DEVICE=auto
HF_REASON_DTYPE=auto
HF_REASON_MAX_NEW_TOKENS=512
HF_REASON_VALIDATION_MAX_NEW_TOKENS=256
HF_REASON_TIMEOUT_SECONDS=120
HF_REASON_ANSWER_MODE=deterministic
HF_REASON_TEMPERATURE=0.0
HF_REASON_TOP_P=0.8
HF_REASON_TOP_K=20
```

For dry runs, the current project uses the local HF path for:

- reasoning and Ask synthesis
- structured validation
- optional ingest-time fact review

These runs may not expose Azure-style token usage values. Treat token usage fields as unavailable when the HF path is selected.

For private Hugging Face models beyond the default reasoning model, keep `HF_TOKEN` set and configure the model fields in `base_config.json` or the environment:

- `HF_REASON_MODEL` for reasoning and Ask dry runs.
- `EMBEDDING_PROVIDER=sentence_transformers` with `EMBEDDING_MODEL=<your-private-embedder>`.
- `RERANKER_PROVIDER=sentence_transformers` with `RERANKER_MODEL=<your-private-cross-encoder>`.

That keeps the dry-run path fully local while still allowing private Hub downloads when permitted by your token.

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
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_VERSION=2024-10-21
HF_TOKEN=...
```

## Service Checks

```powershell
uv run --no-sync multi-agentic-rag db-check
uv run --no-sync multi-agentic-rag chroma-check
uv run --no-sync multi-agentic-rag graph-check
uv run --no-sync multi-agentic-rag health-check
uv run --no-sync multi-agentic-rag azure-check
uv run --no-sync multi-agentic-rag embedding-check
uv run --no-sync multi-agentic-rag reranker-check
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

SIIMCS reference ingest:

```powershell
uv run --no-sync multi-agentic-rag ingest .\documents\inbox\PROJECT_1\SIIMCS_BRD_V1.pdf `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --review-facts
```

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
  --review `
  --show-quality-metrics `
  --explain-retrieval
```

Exhaustive requirement queries enumerate active PostgreSQL ledger records first, then render the full inventory with evidence. Semantic questions use hybrid retrieval across PostgreSQL FTS, Chroma, and Neo4j.

## User Stories

```powershell
uv run --no-sync multi-agentic-rag user-stories `
  --system PROJECT_1 `
  --version v1 `
  --review `
  --explain-generation `
  --show-quality-metrics
```

Combined flow:

```powershell
uv run --no-sync multi-agentic-rag ingest-and-user-stories .\documents\PROJECT_1_BRD_v1.md `
  --system PROJECT_1 `
  --version v1 `
  --review
```

Generated user stories include debug JSON and a trace manifest JSON. Trace manifests record the artifact, workflow/generation context, source document version, requirements, evidence, story ID, config fingerprint, model fingerprint, timestamp, and schema version.

The production story artifact set now includes:

- `<story-id>.yaml`
- `<story-id>.json`
- `run_manifest.json`
- `artifacts/user_stories/story_quality_report.json`
- `artifacts/user_stories/story_quality_report.md`
- `debug/retrieval_trace.json`
- `debug/generation_trace.json`
- `debug/validation_trace.json`
- `debug/provider_errors.json` on failure

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

## Azure Commands

Enterprise Azure run commands:

```powershell
uv run --no-sync multi-agentic-rag azure-check
uv run --no-sync multi-agentic-rag embedding-check
uv run --no-sync multi-agentic-rag reranker-check
uv run --no-sync multi-agentic-rag facts-audit `
  --system PROJECT_1 `
  --version v1 `
  --kb default
uv run --no-sync multi-agentic-rag facts-evaluate `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --golden-file .\tests\fixtures\siimcs_facts_golden.json
uv run --no-sync multi-agentic-rag retrieval-evaluate `
  --dataset .\tests\fixtures\siimcs_retrieval_golden.json `
  --system PROJECT_1 `
  --version v1 `
  --kb default
uv run --no-sync multi-agentic-rag ingest .\documents\inbox\PROJECT_1\SIIMCS_BRD_V1.pdf `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --review-facts
uv run --no-sync multi-agentic-rag ask "What are the minimum and maximum temperature sensor thresholds?" `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --explain-retrieval `
  --show-quality-metrics
uv run --no-sync multi-agentic-rag user-stories `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --review `
  --explain-generation `
  --show-quality-metrics
uv run --no-sync multi-agentic-rag reindex-chroma `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --target-collection "multi_agentic_rag_azure_enterprise_v3"
uv run --no-sync multi-agentic-rag validate-index `
  --collection "multi_agentic_rag_azure_enterprise_v3"
uv run --no-sync multi-agentic-rag activate-index `
  --collection "multi_agentic_rag_azure_enterprise_v3"
```

Azure stories, Ask answers, validation, fact review, and reranking all route through deployment names configured in `base_config.json`.

## Hugging Face Commands

Local/private-model dry runs use the same CLI surface with `--model hf`:

```powershell
uv run --no-sync multi-agentic-rag ingest .\documents\inbox\PROJECT_1\SIIMCS_BRD_V1.pdf `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --model hf `
  --review-facts
uv run --no-sync multi-agentic-rag ask "What are the minimum and maximum temperature sensor thresholds?" `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --model hf `
  --explain-retrieval `
  --show-quality-metrics
uv run --no-sync multi-agentic-rag user-stories `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --model hf `
  --review `
  --explain-generation `
  --show-quality-metrics
```

For HF dry runs, the project keeps CUDA optional and falls back to CPU automatically when CUDA is unavailable.

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

If you change the embedding provider or deployment, create a new collection, reindex, validate, and only then activate the new collection. Do not overwrite the old collection in place.

Current enterprise collection:

```text
multi_agentic_rag_azure_enterprise_v3
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
