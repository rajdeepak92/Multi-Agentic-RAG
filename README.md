# Multi-Agentic RAG

GraphRAG runtime for document ingestion, requirement-ledger discovery, hybrid retrieval,
grounded answers, and user-story generation.

The current repository keeps provider selection independent:

- `REASONING_PROVIDER=openai` uses the public `openai.OpenAI` client.
- `REASONING_PROVIDER=azure_openai` uses `openai.AzureOpenAI`.
- `EMBEDDING_PROVIDER=azure_openai` uses `openai.AzureOpenAI`.
- `RERANKER_PROVIDER=azure_openai` uses `AzureOpenAIReasoningClient` with Azure deployments.

Azure values are machine-local environment settings. Do not place keys or endpoint
secrets in tracked files.

## Configuration

Tracked, non-secret defaults live in [`base_config.json`](./base_config.json). Secret
values live in [`/.env.example`](./.env.example) as a template for the local `.env`.

Azure OpenAI uses:

```dotenv
AZURE_OPENAI_ENDPOINT=https://<azure-resource>.cognitiveservices.azure.com
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

Example provider combinations:

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

## Quick Start

```powershell
uv sync --dev --link-mode=copy
New-Item -ItemType Directory -Force documents, .global_cache, generated | Out-Null
uv run --no-sync multi-agentic-rag db-check
uv run --no-sync multi-agentic-rag chroma-check
uv run --no-sync multi-agentic-rag graph-check
uv run --no-sync multi-agentic-rag azure-check
uv run --no-sync multi-agentic-rag health-check
```

## Common Commands

```powershell
uv run --no-sync multi-agentic-rag ingest .\documents\PROJECT_1_BRD_v1.md --system PROJECT_1 --version v1 --kb default --review
uv run --no-sync multi-agentic-rag retrieve "temperature threshold" --system PROJECT_1 --version v1 --show-graph-paths --show-quality-metrics
uv run --no-sync multi-agentic-rag ask "Summarize the temperature and threshold requirements." --system PROJECT_1 --version v1 --show-quality-metrics --explain-retrieval
uv run --no-sync multi-agentic-rag requirements --system PROJECT_1 --version v1
uv run --no-sync multi-agentic-rag requirements-audit --system PROJECT_1 --version v1
uv run --no-sync multi-agentic-rag requirements-rebuild --system PROJECT_1 --version v1
uv run --no-sync multi-agentic-rag user-stories --system PROJECT_1 --version v1 --show-quality-metrics
```

## Execution Guide

See [`execution.md`](./execution.md) for the full fresh-setup, configuration, validation,
ingestion, retrieval, and user-story workflow.
