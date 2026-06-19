# Execution Commands

Use these commands from the repository root after configuring `.env`.

For Hugging Face-hosted embedding or reranker models, set `HF_TOKEN` in `.env`:

```powershell
HF_TOKEN=hf_your_token_here
```

## Health Checks

```powershell
uv run multi-agentic-rag health-check
uv run multi-agentic-rag db-check
uv run multi-agentic-rag chroma-check
uv run multi-agentic-rag graph-check
```

## Ingest One Document

Supported source types: `.pdf`, `.docx`, `.txt`, `.md`, `.markdown`.

```powershell
uv run multi-agentic-rag ingest .\documents\Document.pdf --system PROJECT_1 --version v1 --kb default
uv run multi-agentic-rag ingest .\documents\Document.docx --system PROJECT_1 --version v1 --kb default
uv run multi-agentic-rag ingest .\documents\Document.txt --system PROJECT_1 --version v1 --kb default
uv run multi-agentic-rag ingest .\documents\Document.md --system PROJECT_1 --version v1 --kb default
```

## Ingest A Directory

```powershell
uv run multi-agentic-rag ingest-directory .\documents\inbox --system PROJECT_1 --version v1 --kb default
```

Disable recursive scanning when needed:

```powershell
uv run multi-agentic-rag ingest-directory .\documents\inbox --system PROJECT_1 --version v1 --kb default --no-recursive
```

## V1 To V3 Lifecycle

```powershell
uv run multi-agentic-rag ingest .\documents\BRD_v1.pdf --system PROJECT_1 --version v1 --kb default
uv run multi-agentic-rag ingest .\documents\BRD_v2.pdf --system PROJECT_1 --version v2 --kb default
uv run multi-agentic-rag ingest .\documents\BRD_v3.pdf --system PROJECT_1 --version v3 --kb default
```

When a newer version is valid, PostgreSQL keeps the durable lineage, Chroma refreshes old chunks as `superseded`, and Neo4j marks old `DocumentVersion`, `Chunk`, and `Fact` nodes as `superseded`.

## Missing Version Fallback

If `v2` is ingested before `v1`, the command completes with a warning and stores the ingest as `v1`:

```powershell
uv run multi-agentic-rag ingest .\documents\BRD_v2.pdf --system PROJECT_1 --version v2 --kb default
```

Expected warning pattern:

```text
WARN Requested v2, but v1 is not available; treating this ingest as v1.
```

If `v7` is ingested while `v6` is not active, the command completes with a warning and stores the ingest as `v6`:

```powershell
uv run multi-agentic-rag ingest .\documents\BRD_v7.pdf --system PROJECT_1 --version v7 --kb default
```

Expected warning pattern:

```text
WARN Requested v7, but v6 is not active ... treating this ingest as v6.
```

## Clean One System

This deletes matching rows/vectors/nodes from PostgreSQL, ChromaDB, and Neo4j for one system.

```powershell
uv run multi-agentic-rag clean-system-state --system PROJECT_1 --yes
```

Limit cleanup to one knowledge base:

```powershell
uv run multi-agentic-rag clean-system-state --system PROJECT_1 --kb default --yes
```

## Delete All Data And Cache

This deletes all GraphRAG data from PostgreSQL, ChromaDB, and Neo4j, then removes runtime/cache directories such as `.multi_agentic_rag` and `.cache`.

```powershell
uv run multi-agentic-rag clean-system-state --all --delete-cache --yes
```

Run health checks again before re-ingestion:

```powershell
uv run multi-agentic-rag health-check
```

## Retrieve Evidence

Current active evidence only:

```powershell
uv run multi-agentic-rag retrieve "temperature threshold" --system PROJECT_1 --kb default --top-k 5
```

Inspect a historical version explicitly:

```powershell
uv run multi-agentic-rag retrieve "temperature threshold" --system PROJECT_1 --kb default --version v1 --top-k 5
```
