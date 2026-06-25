# Execution Guide

This is the end-to-end operator guide for the current root-only GraphRAG runtime.
It assumes Python 3.12+, `uv`, PostgreSQL, Chroma, Neo4j, and the repository root at
`D:\Multi-Agentic-RAG`.

## 1. Fresh Setup

From a clean checkout, install dependencies and create the local runtime folders:

```powershell
uv sync --dev --link-mode=copy
New-Item -ItemType Directory -Force documents, .global_cache, generated | Out-Null
```

Use `.env.example` as the secret template and keep tracked config non-secret:

```powershell
Copy-Item .env.example .env
```

Edit `.env` locally for the machine you are on. Do not place secret values in
`base_config.json`.

## 2. Configuration

`base_config.json` is the tracked runtime profile. It should contain provider
selection, deployment names, and other non-secret defaults only.

Azure OpenAI uses machine-local environment variables:

```dotenv
AZURE_OPENAI_ENDPOINT=https://<azure-resource>.cognitiveservices.azure.com
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

Provider combinations stay independent. These are the three common patterns:

```dotenv
REASONING_PROVIDER=openai
EMBEDDING_PROVIDER=sentence_transformers
RERANKER_PROVIDER=none
```

```dotenv
REASONING_PROVIDER=azure_openai
EMBEDDING_PROVIDER=azure_openai
RERANKER_PROVIDER=azure_openai
```

```dotenv
REASONING_PROVIDER=openai
EMBEDDING_PROVIDER=azure_openai
RERANKER_PROVIDER=azure_openai
```

The Azure reasoning client defaults to `AZURE_OPENAI_REASONING_API_STYLE=chat_completions`.
Switch to `responses` only if the configured Azure deployment supports it.

## 3. Static Checks

Run the local readiness checks before ingesting anything:

```powershell
uv run --no-sync multi-agentic-rag db-check
uv run --no-sync multi-agentic-rag chroma-check
uv run --no-sync multi-agentic-rag graph-check
uv run --no-sync multi-agentic-rag azure-check
uv run --no-sync multi-agentic-rag embedding-check
uv run --no-sync multi-agentic-rag reranker-check
uv run --no-sync multi-agentic-rag health-check
```

What to look for:

```text
db-check
  PASS means PostgreSQL connectivity and lexical readiness are okay.
  FAIL usually means a DSN, extension, or migration problem.

chroma-check
  PASS means the local vector store path and collection are reachable.

graph-check
  PASS means Neo4j is reachable.

azure-check
  Shows endpoint, API version, API key presence, client class, API style,
  and deployment routing without making a live request.

embedding-check
  Shows the active embedding provider, model or deployment, and fingerprint.

reranker-check
  Shows the active reranking provider and the instantiated reranker class.

health-check
  Summarizes PostgreSQL, Chroma, and Neo4j together.
```

## 4. Ingestion

Ingest a document into PostgreSQL, Chroma, and Neo4j:

```powershell
uv run --no-sync multi-agentic-rag ingest .\documents\PROJECT_1_BRD_v1.md `
  --system PROJECT_1 `
  --version v1 `
  --kb default `
  --review
```

Useful notes:

- `--review` is deterministic and does not call a model.
- `--review-facts` is opt-in and uses the configured reasoning provider.
- The command writes the ingestion result and any review events to the console.

For a directory batch:

```powershell
uv run --no-sync multi-agentic-rag ingest-directory .\documents `
  --system PROJECT_1 `
  --version v1 `
  --review
```

Expected output locations:

- `generated/` for user-story artifacts.
- `.global_cache/` for runtime caches.
- The configured PostgreSQL database for authoritative records.

## 5. Requirement Discovery

The requirement ledger commands are the cleanest way to inspect what ingestion found:

```powershell
uv run --no-sync multi-agentic-rag requirements --system PROJECT_1 --version v1
uv run --no-sync multi-agentic-rag requirements-audit --system PROJECT_1 --version v1
uv run --no-sync multi-agentic-rag requirements-rebuild --system PROJECT_1 --version v1
```

Use them in this order when you need to compare stored requirements, evidence links,
and the regenerated ledger state.

## 6. Ask And Retrieval

Ask a grounded question:

```powershell
uv run --no-sync multi-agentic-rag ask "Summarize the temperature and threshold requirements." `
  --system PROJECT_1 `
  --version v1 `
  --show-quality-metrics `
  --explain-retrieval
```

For a retrieval-only view with graph paths:

```powershell
uv run --no-sync multi-agentic-rag retrieve "temperature threshold" `
  --system PROJECT_1 `
  --version v1 `
  --show-graph-paths `
  --show-quality-metrics
```

What to look for:

- retrieval sources from PostgreSQL, Chroma, and Neo4j
- graph traversal paths when graph hits exist
- quality metrics attached to the answer
- the final answer and citation list

## 7. User Stories

Generate user stories from the ingested version:

```powershell
uv run --no-sync multi-agentic-rag user-stories `
  --system PROJECT_1 `
  --version v1 `
  --show-quality-metrics
```

Add `--review` if you want deterministic review-event tables printed alongside the
story generation result.

Expected output:

- YAML or console-rendered story artifacts
- traceability and coverage metadata
- any quality gate failures required by the current settings

## 8. Azure Checks With Live Access

The default Azure checks are static only. If you want to verify live Azure access,
run an explicit command path that makes a request. Keep this opt-in and separate
from normal health checks.

The current code path is designed so unit tests and normal CLI diagnostics do not
need live Azure access.

## 9. Common Failure Modes

- `AZURE_OPENAI_ENDPOINT` missing or malformed: fix the local `.env`.
- `AZURE_OPENAI_API_VERSION` missing: set the Azure REST API contract version.
- `azure_openai.base_url` still present in config: migrate to `AZURE_OPENAI_ENDPOINT`.
- `db-check` fails but Azure checks pass: the problem is PostgreSQL, not Azure.
- `health-check` fails on Neo4j: fix the graph service before blaming retrieval.

## 10. Where To Inspect Results

- Ingestion result summaries appear in the CLI output and are persisted in the runtime store.
- User-story artifacts are written under `generated/`.
- The project cache lives under `.global_cache/`.
- Azure preflight output is available from `azure-check`.

