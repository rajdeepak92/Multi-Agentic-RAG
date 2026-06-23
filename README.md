# Multi-Agentic RAG

GraphRAG runtime for enterprise QA automation. The project ingests versioned
requirements documents into synchronized PostgreSQL, ChromaDB, and Neo4j stores,
builds a canonical Requirement Ledger with evidence, answers grounded questions,
and generates traceable user-story artifacts.

The public business-agent surface is intentionally small:

- `KnowledgeBaseIngestionAgent`: parses source documents, chunks evidence,
  extracts facts and requirements, persists PostgreSQL lineage, indexes Chroma,
  and projects Neo4j graph records.
- `UserStoryGenerationAgent`: enumerates the Requirement Ledger, enriches each
  requirement with GraphRAG evidence, generates bounded user-story batches, and
  publishes a deterministic requirement-to-story coverage matrix.

## Current Capabilities

- Version-scoped ingestion for PDF, DOCX, TXT, Markdown, and `.markdown` files.
- PostgreSQL as the authoritative store for documents, chunks, facts,
  requirements, requirement evidence, and story coverage.
- `pg_textsearch` BM25 lexical retrieval with readiness checks.
- Chroma vector retrieval with model fingerprint metadata.
- Neo4j projection for documents, versions, chunks, requirements, evidence spans,
  facts, and user-story coverage edges.
- Deterministic Requirement Ledger extraction for:
  - functional requirements such as `BR-SEN-001`, `BR-COM 001`,
    `BR-COM-001`, `BR-COM_001`, and Unicode dash variants;
  - non-functional requirements;
  - rule-based automation scenarios;
  - `AC-*` acceptance criteria;
  - Definition-of-Done statements;
  - scope constraints.
- Exhaustive requirement questions such as "list all requirements" enumerate the
  PostgreSQL ledger instead of relying on semantic top-k retrieval.
- Normal semantic questions continue to use hybrid PostgreSQL, Chroma, Neo4j,
  fusion, and optional reranking.
- Ledger inspection, audit, and rebuild commands.
- User-story generation starts from exact active story-driving requirements,
  not from search results.
- Coverage artifacts for generated stories:
  - `requirements_inventory.json`
  - `requirements_inventory.md`
  - `requirement_story_coverage.json`
  - `requirement_story_coverage.csv`
  - `retrieval_trace.json`
- Local Hugging Face reasoning support with CPU fallback and CUDA auto-selection
  when the installed PyTorch build exposes CUDA.
- OpenAI and Gemini provider configuration remains available through config.
- Backend cleanup commands for PostgreSQL, Chroma, Neo4j, or the full system.

## Repository And Runtime Shape

Use the repository root as the runtime root.

```text
D:\Multi-Agentic-RAG
|-- base_config.json              # local non-secret runtime config
|-- base_config.example.json      # tracked example config
|-- .env                          # local secrets only
|-- .env.example                  # tracked secret-name template
|-- documents\                    # source documents
|-- .global_cache\                # HF, Torch, Chroma, and runtime cache
|-- generated\                    # generated stories, audits, traces
|-- migrations\                   # Alembic migrations
|-- src\multi_agentic_rag\        # application package
|-- tests\                        # pytest suite
```

Do not store secrets in `base_config.json`. Secret values belong in `.env`.

## Prerequisites

- Windows PowerShell or an equivalent shell.
- Python 3.12 or newer.
- `uv`.
- PostgreSQL with `pg_textsearch` support. Tiger Cloud works when the connected
  database supports the extension.
- Neo4j reachable at the configured Bolt URI.
- A local Chroma directory is managed by the application; no separate Chroma
  server is required for the current default setup.
- Optional NVIDIA GPU with a CUDA-enabled PyTorch install.

## Fresh Setup

Clone and enter the repository:

```powershell
git clone https://github.com/rajdeepak92/Multi-Agentic-RAG.git
cd Multi-Agentic-RAG
```

Create and activate a named virtual environment:

```powershell
uv venv .venv --prompt multi-agentic-rag
.\.venv\Scripts\Activate.ps1
```

Install the development environment.

CPU-only local runtime:

```powershell
uv sync --dev --extra hf-reasoning --extra cpu --link-mode=copy
```

NVIDIA GPU runtime:

```powershell
uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy
```

The GPU path keeps `hf_device`, `embeddings.device`, and `reranking.device` set
to `auto`. CUDA is used only when `torch.cuda.is_available()` is true; otherwise
the runtime falls back to CPU.

## Configure Runtime

Create local config files:

```powershell
Copy-Item base_config.example.json base_config.json
Copy-Item .env.example .env
```

Edit `.env` with secret values only:

```dotenv
POSTGRES_DSN=postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>
OPENAI_API_KEY=<optional_openai_key>
HF_TOKEN=<optional_huggingface_token>
GEMINI_API_KEY=<optional_gemini_key>
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<neo4j_password>
NEO4J_DATABASE=neo4j
```

Edit `base_config.json` for non-secret runtime settings:

```json
{
  "paths": {
    "cache_dir": ".global_cache",
    "documents_dir": "documents",
    "generated_dir": "generated"
  },
  "postgres": {
    "retry_count": 2,
    "retry_backoff_seconds": 1.0,
    "ssl_mode": "require"
  },
  "neo4j": {
    "uri": "bolt://127.0.0.1:7687",
    "username": "neo4j",
    "database": "neo4j",
    "graphrag_required": true
  },
  "reasoning": {
    "provider": "huggingface",
    "hf_model": "Qwen/Qwen3-0.6B",
    "hf_device": "auto",
    "hf_answer_mode": "deterministic",
    "hf_temperature": 0.0
  },
  "embeddings": {
    "provider": "sentence_transformers",
    "model": "BAAI/bge-m3",
    "device": "auto"
  },
  "reranking": {
    "provider": "none",
    "device": "auto"
  }
}
```

Important configuration fields:

- `retrieval.answer_top_k`: default semantic QA retrieval limit.
- `retrieval.answer_max_evidence`: maximum bounded evidence records for answer
  synthesis.
- `retrieval.answer_max_snippets`: maximum snippets shown by extractive answers.
- `user_stories.requirement_batch_size`: ledger records per generation batch.
- `user_stories.max_stories_per_batch`: maximum stories expected per batch.
- `user_stories.coverage_required_types`: requirement types that must be covered
  or explicitly deferred.
- `user_stories.allow_partial_coverage`: when `false`, publication fails if a
  coverage-required requirement remains missing.
- `lexical.backend`: keep `pg_textsearch` for BM25 lexical retrieval.
- `retrieval.required_sources`: keep `postgres`, `chroma`, and `neo4j` when the
  full GraphRAG stack is required.

## Initialize Database Schema

Run migrations after PostgreSQL is configured:

```powershell
uv run --no-sync python -m alembic upgrade head
```

If your machine blocks the `alembic` executable shim, use the `python -m alembic`
form above. The schema includes the canonical Requirement Ledger,
requirement-evidence spans, and requirement-coverage tables.

## Validate Services

Run the checks before ingestion:

```powershell
uv run --no-sync multi-agentic-rag db-check
uv run --no-sync multi-agentic-rag chroma-check
uv run --no-sync multi-agentic-rag graph-check
uv run --no-sync multi-agentic-rag health-check
uv run --no-sync multi-agentic-rag hf-check
```

Expected readiness:

- `db-check` must pass PostgreSQL connectivity, Alembic revision, `pg_textsearch`,
  and BM25 index readiness.
- `chroma-check` must pass collection readiness.
- `graph-check` must connect to Neo4j.
- `health-check` aggregates PostgreSQL, Chroma, and Neo4j.
- `hf-check` reports local Hugging Face, Torch, and CUDA availability.

If `graph-check` fails with connection refused, start Neo4j and rerun the check.

## Ingest Documents

Ingest one document:

```powershell
uv run --no-sync multi-agentic-rag ingest `
  ".\documents\inbox\PROJECT_1\SIIMCS_BRD_V1.pdf" `
  --system PROJECT_1 `
  --version v1 `
  --kb default
```

Ingest a directory:

```powershell
uv run --no-sync multi-agentic-rag ingest-directory `
  ".\documents\inbox\PROJECT_1" `
  --system PROJECT_1 `
  --version v1 `
  --kb default
```

Run optional LLM fact review during ingestion:

```powershell
uv run --no-sync multi-agentic-rag ingest `
  ".\documents\inbox\PROJECT_1\SIIMCS_BRD_V1.pdf" `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --review-facts
```

Normal ingestion is deterministic and does not require local Hugging Face
generation per chunk.

## Inspect And Audit Requirements

List exact ledger records:

```powershell
uv run --no-sync multi-agentic-rag requirements `
  --system PROJECT_1 `
  --version v1 `
  --kb default
```

Filter and write JSON:

```powershell
uv run --no-sync multi-agentic-rag requirements `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --type non_functional `
  --format json `
  --output .\generated\requirements\PROJECT_1\v1-nfr.json
```

Audit ledger completeness and coverage readiness:

```powershell
uv run --no-sync multi-agentic-rag requirements-audit `
  --system PROJECT_1 `
  --version v1 `
  --kb default
```

The audit reports:

- counts by requirement type;
- duplicate IDs;
- requirements without evidence;
- acceptance criteria without links;
- story-driving requirements without stories;
- unsupported or malformed extraction records.

Rebuild the ledger from already stored chunks without deleting PostgreSQL,
Chroma, Neo4j, or document lineage:

```powershell
uv run --no-sync multi-agentic-rag requirements-rebuild `
  --system PROJECT_1 `
  --version v1 `
  --kb default
```

Use `requirements-rebuild` after upgrading from an older schema or when stored
documents were ingested before the expanded ledger extractor existed.

## Ask Questions

Exhaustive requirement questions enumerate PostgreSQL ledger records:

```powershell
uv run --no-sync multi-agentic-rag ask `
  "Summarize all requirements and business rules." `
  --system PROJECT_1 `
  --version v1 `
  --kb default
```

The exhaustive path includes counts, every explicit ID, generated canonical IDs
for unnumbered records, pages, chunk references, and inventory artifacts when
needed.

Normal semantic questions use hybrid GraphRAG retrieval:

```powershell
uv run --no-sync multi-agentic-rag ask `
  "Which controls protect safety-critical actions?" `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --top-k 10
```

`--top-k` affects semantic QA retrieval. It does not control exhaustive ledger
discovery.

## Generate User Stories

Generate user stories from the exact Requirement Ledger:

```powershell
uv run --no-sync multi-agentic-rag user-stories `
  --system PROJECT_1 `
  --version v1 `
  --kb default
```

Generate stories immediately after ingesting a document:

```powershell
uv run --no-sync multi-agentic-rag ingest-and-user-stories `
  ".\documents\inbox\PROJECT_1\SIIMCS_BRD_V1.pdf" `
  --system PROJECT_1 `
  --version v1 `
  --kb default
```

The user-story workflow:

1. Validates dependency readiness.
2. Enumerates active story-driving requirements from PostgreSQL.
3. Loads one-to-many evidence spans.
4. Groups requirements into deterministic batches.
5. Uses GraphRAG only for enrichment and validation.
6. Generates or falls back to deterministic ledger-backed stories.
7. Writes coverage artifacts.
8. Persists coverage in PostgreSQL.
9. Projects `UserStory-[:COVERS]->Requirement` edges to Neo4j.

Publication fails when `user_stories.allow_partial_coverage` is `false` and any
coverage-required requirement remains missing.

## Retrieve Evidence

Inspect hybrid retrieval results directly:

```powershell
uv run --no-sync multi-agentic-rag retrieve `
  "security controls for automation rules" `
  --system PROJECT_1 `
  --version v1 `
  --kb default
```

Retrieval output labels lexical score, vector score, graph score, fusion score,
reranker score, and final rank when those values are available.

## Natural-Language Routing

The `run` command routes a natural-language task through the workflow planner:

```powershell
uv run --no-sync multi-agentic-rag run `
  "Generate user stories for PROJECT_1 v1" `
  --system PROJECT_1 `
  --version v1 `
  --kb default
```

Prefer explicit commands for repeatable operations and `run` for exploratory
operator workflows.

## Cleanup Commands

Use cleanup commands intentionally. They remove indexed or persisted runtime
state for the selected scope.

```powershell
uv run --no-sync multi-agentic-rag clean-postgres-state --system PROJECT_1 --kb default
uv run --no-sync multi-agentic-rag clean-chroma-state --system PROJECT_1 --kb default
uv run --no-sync multi-agentic-rag clean-neo4j-state --system PROJECT_1 --kb default
uv run --no-sync multi-agentic-rag clean-system-state --system PROJECT_1 --kb default
```

Do not use cleanup as part of normal migrations. Use Alembic migrations and
`requirements-rebuild` instead.

## Generated Outputs

Generated files are written under `generated\`.

Typical user-story run output:

```text
generated\runs\<run_id>\artifacts\user_stories\
|-- user_stories.yaml
|-- user_stories.json
|-- requirements_inventory.json
|-- requirements_inventory.md
|-- requirement_story_coverage.json
|-- requirement_story_coverage.csv
|-- retrieval_trace.json
```

Typical exhaustive requirement-answer output:

```text
generated\requirements\<system>\<kb>\<version>\<timestamp>\
|-- requirements_inventory.json
|-- requirements_inventory.md
```

## Quality Checks

Run the configured quality gates:

```powershell
uv lock --check
uv run --no-sync python -m alembic upgrade head
uv run --no-sync pytest
uv run --no-sync ruff check .
uv run --no-sync mypy
uv run --no-sync multi-agentic-rag db-check
uv run --no-sync multi-agentic-rag chroma-check
uv run --no-sync multi-agentic-rag graph-check
uv run --no-sync multi-agentic-rag health-check
```

If Neo4j is not running, `graph-check`, `health-check`, `requirements-rebuild`
graph projection, and `user-stories` publication can fail even when PostgreSQL,
Chroma, extraction, tests, and migrations are healthy.

## Troubleshooting

PostgreSQL readiness failure:

1. Confirm `POSTGRES_DSN` points at the intended database.
2. Confirm the server supports `pg_textsearch`.
3. Run `uv run --no-sync python -m alembic upgrade head`.
4. Rerun `uv run --no-sync multi-agentic-rag db-check`.

Neo4j connection refused:

1. Start Neo4j.
2. Confirm `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, and
   `NEO4J_DATABASE`.
3. Rerun `uv run --no-sync multi-agentic-rag graph-check`.

CUDA unavailable:

1. Run `uv run --no-sync multi-agentic-rag hf-check`.
2. Confirm the active virtual environment installed the `gpu` extra.
3. Confirm `torch.cuda.is_available()` is true in the same environment.
4. Keep device fields set to `auto` unless you are intentionally forcing CPU.

Exhaustive requirement answer is incomplete:

1. Run `requirements-audit`.
2. Run `requirements-rebuild` for documents ingested before the ledger migration.
3. Reingest the source document if chunks were never stored or the source changed.

## Backward Compatibility

- The command name remains `multi-agentic-rag`.
- Existing `ingest`, `ingest-directory`, `ask`, `retrieve`, `user-stories`,
  `ingest-and-user-stories`, and `run` commands are preserved.
- `--model` remains a compatibility override. The preferred provider selection
  is `base_config.json -> reasoning.provider`.
- Existing GraphRAG data is not deleted by migrations.
- Previously ingested documents may need `requirements-rebuild` or reingestion
  to populate the expanded ledger and evidence structures.
