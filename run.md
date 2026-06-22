# Multi-Agentic RAG Runbook

Run commands from the repository root:

```powershell
cd D:\Multi-Agentic-RAG
```

The CLI entry point is:

```powershell
uv run --no-sync multi-agentic-rag --help
```

The package also exposes QA automation aliases after entrypoints are refreshed:

```powershell
uv run --no-sync qa-ingest --help
uv run --no-sync qa-user-stories --help
uv run --no-sync qa-doctor
```

Expected command list shape:

```text
ingest
ingest-directory
clean-system-state
clean-postgres-state
clean-chroma-state
clean-neo4j-state
retrieve
ask
user-stories
ingest-and-user-stories
run
db-check
chroma-check
graph-check
health-check
hf-check
```

## Setup

Install dependencies and create `.env`:

```powershell
uv sync --dev --link-mode=copy
Copy-Item .env.example .env
```

`base_config.json` is the root runtime profile for non-secret settings. Minimum `.env` shape:

```env
POSTGRES_DSN=postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>
OPENAI_API_KEY=<your_openai_api_key>
HF_TOKEN=<your_huggingface_token>
GEMINI_API_KEY=<your_gemini_api_key>
NEO4J_PASSWORD=<your_neo4j_password>
```

Expected setup result:

```text
Dependencies are installed.
.env exists locally.
.global_cache is created on the first CLI command.
No secrets are written to tracked files.
```

PostgreSQL and Neo4j connection strings still point to running services. This repo only centralizes app-owned cache paths, model downloads, Chroma persistence, and runtime files under `.global_cache/`.

## Root Runtime

Initialize root config only when `base_config.json` is missing:

```powershell
uv run --no-sync multi-agentic-rag init .
```

Use `base_config.json` for non-secret defaults and keep secret values in `.env`. Runtime commands resolve config in this order: CLI flags, environment variables, root `base_config.json`, defaults. Normal runs do not rewrite `base_config.json`.

One-time local HF/GPU setup:

```powershell
uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy
```

Normal development runs after setup:

```powershell
uv run --no-sync qa-doctor
uv run --no-sync qa-ingest .\documents\PROJECT_1_BRD_v1.md --system PROJECT_1 --version v1
uv run --no-sync qa-user-stories --system PROJECT_1 --version v1
uv run --no-sync multi-agentic-rag health-check
```

`--cuda` enables GPU preflight and device planning. `--cuda-required` fails the run if CUDA is unavailable instead of falling back to CPU. For broken Torch `RECORD` metadata or hardlink issues, recreate `.venv` and use `UV_LINK_MODE=copy` or `--link-mode=copy`.

## Migrations

Apply all schema migrations:

```powershell
uv run --no-sync alembic upgrade head
```

Expected output shape:

```text
Running upgrade ... 20260618_0001
Running upgrade ... 20260619_0002
Running upgrade ... 20260620_0003
Running upgrade ... 20260620_0004
```

PostgreSQL BM25 readiness uses `pg_textsearch` and `idx_chunks_text_bm25`:

```sql
SELECT extname FROM pg_extension WHERE extname = 'pg_textsearch';
SELECT to_regclass('idx_chunks_text_bm25');
```

Native PostgreSQL FTS is only the explicit fallback when `BM25_BACKEND=postgres_fts`.

## Health Checks

Check each backend:

```powershell
uv run --no-sync multi-agentic-rag db-check
uv run --no-sync multi-agentic-rag chroma-check
uv run --no-sync multi-agentic-rag graph-check
```

Expected output shape:

```text
PostgreSQL: PASS - PostgreSQL connection and pg_textsearch BM25 index are ready.
Chroma: PASS - Chroma collection is ready.
Neo4j: PASS - Neo4j graph-check PASS.
```

Check all backends together:

```powershell
uv run --no-sync multi-agentic-rag health-check
```

Expected output shape:

```text
GraphRAG Health
Service      Status   Detail
PostgreSQL   PASS     ...
Chroma       PASS     ...
Neo4j        PASS     ...
```

## Cleanup

Combined cleanup keeps PostgreSQL, ChromaDB, and Neo4j aligned:

```powershell
uv run --no-sync multi-agentic-rag clean-system-state --system PROJECT_1 --kb default --yes
uv run --no-sync multi-agentic-rag clean-system-state --system PROJECT_1 --yes
uv run --no-sync multi-agentic-rag clean-system-state --all --yes
uv run --no-sync multi-agentic-rag clean-system-state --all --delete-cache --yes
```

Expected combined output shape:

```text
Clean System State
Target                Deleted
PostgreSQL rows       42
Chroma vectors        18
Neo4j nodes           67
Runtime/cache paths   0
```

Backend-specific cleanup:

```powershell
uv run --no-sync multi-agentic-rag clean-postgres-state --system PROJECT_1 --kb default --yes
uv run --no-sync multi-agentic-rag clean-chroma-state --system PROJECT_1 --kb default --yes
uv run --no-sync multi-agentic-rag clean-neo4j-state --system PROJECT_1 --kb default --yes
```

All-data backend-specific cleanup:

```powershell
uv run --no-sync multi-agentic-rag clean-postgres-state --all --yes
uv run --no-sync multi-agentic-rag clean-chroma-state --all --yes
uv run --no-sync multi-agentic-rag clean-neo4j-state --all --yes
```

Expected individual output shapes:

```text
Clean PostgreSQL State
Target            Deleted
PostgreSQL rows   42

Clean Chroma State
Target           Deleted
Chroma vectors   18

Clean Neo4j State
Target        Deleted
Neo4j nodes   67
```

Cleanup option rules:

```text
Provide either --system or --all.
Do not combine --all with --system.
Do not combine --kb with --all.
--delete-cache is available only on clean-system-state and requires --all.
--delete-cache deletes .global_cache plus legacy runtime/cache paths.
Every cleanup command prompts unless --yes is supplied.
```

## Ingestion

Single document:

```powershell
uv run --no-sync multi-agentic-rag ingest .\documents\BRD_v1.pdf --system PROJECT_1 --version v1 --kb default
```

Help contract:

```powershell
uv run --no-sync multi-agentic-rag ingest --help
```

Important options:

```text
DOCUMENT_PATH is required.
--system is required.
--version is required.
--kb defaults to default.
--model defaults to openai and accepts openai or hf.
--review-facts defaults off. Add --review-facts only when LLM fact review is required.
```

Expected successful output shape:

```text
document_id: ...
document_version_id: ...
chunks_count: 18
facts_count: 30
deltas_count: 0
postgres_status: succeeded
chroma_status: indexed:18
neo4j_status: projected
bm25_status: ready
ingestion_run_id: ...
```

What happens:

```text
resolve -> validate version -> hash -> copy source -> parse -> chunk -> manifest
-> extract facts -> optional fact review -> deltas -> PostgreSQL persist
-> Chroma index -> Neo4j projection -> validation -> run succeeded
```

## Directory Ingestion

Recursive directory ingest:

```powershell
uv run --no-sync multi-agentic-rag ingest-directory .\documents\inbox --system PROJECT_1 --version v1 --kb default
```

Non-recursive directory ingest:

```powershell
uv run --no-sync multi-agentic-rag ingest-directory .\documents\inbox --system PROJECT_1 --version v1 --kb default --no-recursive
```

Help contract:

```powershell
uv run --no-sync multi-agentic-rag ingest-directory --help
```

Expected output shape:

```text
Directory Ingestion
Document        Status   Document Version ID   Chunks   Facts   Warnings
BRD_v1.pdf      PASS     ...                   18       30
SRS_v1.docx     PASS     ...                   12       20
```

Supported suffixes are `.pdf`, `.docx`, `.txt`, `.md`, and `.markdown`.

## User-Story Generation

Generate stories from an already ingested version:

```powershell
uv run --no-sync multi-agentic-rag user-stories --system PROJECT_1 --version v1 --kb default
```

Help contract:

```powershell
uv run --no-sync multi-agentic-rag user-stories --help
```

Expected output shape:

```text
artifact: generated\PROJECT_1\default\v1\user_stories\US-001.yaml
artifact: generated\PROJECT_1\default\v1\user_stories\US-002.yaml
```

Expected file outputs:

```text
generated/<system>/<kb>/<version>/user_stories/<story-id>.yaml
generated/<system>/<kb>/<version>/debug/<story-id>.json
```

The debug JSON contains source document IDs, document version IDs, chunk IDs, graph paths, retrieval scores, prompt version, model, and validation status.

## Ingest And User Stories

Use the composed command when one source should be ingested and immediately used for story generation:

```powershell
uv run --no-sync multi-agentic-rag ingest-and-user-stories .\documents\BRD_v1.pdf --system PROJECT_1 --version v1 --kb default
```

Help contract:

```powershell
uv run --no-sync multi-agentic-rag ingest-and-user-stories --help
```

Expected output shape:

```text
Ingested document version ...
artifact: generated\PROJECT_1\default\v1\user_stories\US-001.yaml
```

This command performs `AgentIngestDocument` first, then `AgentUserStoryBuilder`.

## Natural-Language Run

Use `run` for LangGraph routing, planning, dispatch, validation, and final response:

```powershell
uv run --no-sync multi-agentic-rag run "ingest this document and create user stories" --system PROJECT_1 --kb default --version v1 --document .\documents\BRD_v1.pdf
```

Ask through the workflow:

```powershell
uv run --no-sync multi-agentic-rag run "answer what changed in the temperature threshold" --system PROJECT_1 --kb default --version v2
```

Help contract:

```powershell
uv run --no-sync multi-agentic-rag run --help
```

Expected output shapes:

```text
Ingested document version ...
Generated user stories.
```

or:

```text
Missing required slot: system
Missing required slot: version
```

## Retrieval And Ask

Retrieve ranked evidence:

```powershell
uv run --no-sync multi-agentic-rag retrieve "temperature threshold" --system PROJECT_1 --kb default --top-k 5
uv run --no-sync multi-agentic-rag retrieve "temperature threshold" --system PROJECT_1 --kb default --version v1 --top-k 5 --show-graph-paths
```

Help contract:

```powershell
uv run --no-sync multi-agentic-rag retrieve --help
```

Expected retrieval output shape:

```text
Retrieval Results
Score    Version   Source      Page   Signals             Text
0.0489   v1        BRD_v1.pdf  3      bm25,graph,vector   ...

Graph Paths
chunk-id
- requirement match: ...
```

`Signals` can include:

```text
bm25
fts
vector
graph
```

`bm25` means PostgreSQL `pg_textsearch` BM25 over stored chunk text. `fts` appears only when `BM25_BACKEND=postgres_fts`.

Ask with model synthesis:

```powershell
uv run --no-sync multi-agentic-rag ask "What is the temperature threshold?" --system PROJECT_1 --kb default --version v1
```

Help contract:

```powershell
uv run --no-sync multi-agentic-rag ask --help
```

Expected ask output shape:

```text
The temperature threshold is ...
```

If evidence is empty or untraceable:

```text
I could not find this in the selected project documents
```

## Hugging Face Mode

Install local reasoning dependencies:

```powershell
# CPU install
uv sync --dev --extra hf-reasoning --extra cpu --link-mode=copy
uv run --no-sync multi-agentic-rag hf-check

# NVIDIA GPU install
uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy
uv run --no-sync multi-agentic-rag hf-check
```

Use `--model hf` on reasoning commands:

```powershell
uv run --no-sync multi-agentic-rag ingest .\documents\BRD_v1.pdf --system PROJECT_1 --version v1 --kb default --model hf
uv run --no-sync multi-agentic-rag ingest .\documents\BRD_v1.pdf --system PROJECT_1 --version v1 --kb default --model hf --review-facts
uv run --no-sync multi-agentic-rag ingest-directory .\documents\inbox --system PROJECT_1 --version v1 --kb default --model hf
uv run --no-sync multi-agentic-rag ask "What is the temperature threshold?" --system PROJECT_1 --kb default --version v1 --model hf
uv run --no-sync multi-agentic-rag user-stories --system PROJECT_1 --version v1 --kb default --model hf
uv run --no-sync multi-agentic-rag ingest-and-user-stories .\documents\BRD_v1.pdf --system PROJECT_1 --version v1 --kb default --model hf
uv run --no-sync multi-agentic-rag run "ingest this document and create user stories" --system PROJECT_1 --kb default --version v1 --document .\documents\BRD_v1.pdf --model hf
```

Relevant `base_config.json` keys:

```json
{
  "reasoning": {
    "hf_model": "Qwen/Qwen3-0.6B",
    "hf_device": "cuda",
    "hf_answer_mode": "deterministic"
  },
  "embeddings": {
    "model": "BAAI/bge-m3",
    "device": "cuda"
  },
  "reranking": {
    "provider": "none"
  }
}
```

Expected behavior:

```text
The command uses local Hugging Face structured-output validation.
The command does not require OPENAI_API_KEY for the reasoning call.
The command still requires PostgreSQL, ChromaDB, and Neo4j.
Ingest fact review is skipped unless --review-facts is supplied.
ask --model hf uses deterministic structured answers by default and does not load Qwen unless HF_REASON_ANSWER_MODE=generative.
Threshold questions select the requested sensor row and render normal, minimum, maximum, and critical bands instead of echoing full retrieved chunks.
Reranking is off by default for fast one-shot CLI runs; enable RERANKER_PROVIDER=sentence_transformers only when you want the extra cross-encoder pass.
```

The runtime does not silently fall back from OpenAI to Hugging Face. If OpenAI returns quota errors, rerun the same command with `--model hf`.

Load-test the configured tokenizer/model only after the dependency check passes:

```powershell
uv run --no-sync multi-agentic-rag hf-check --load-model
```

Troubleshooting:

```text
If device_map="auto" requires accelerate, run uv sync --dev --extra hf-reasoning --extra cpu --link-mode=copy or uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy and retry.
If nvidia-smi is present but hf-check reports torch 2.x+cpu or CUDA not available, run uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy.
Use uv run --no-sync multi-agentic-rag ... after the chosen sync profile.
HF_REASON_DEVICE=auto is the default and requires accelerate.
HF_REASON_DEVICE=cpu avoids device_map on CPU-only machines; cuda or cuda:0 forces GPU on CUDA-ready installs.
EMBEDDING_DEVICE and RERANKER_DEVICE support auto, cpu, cuda, and cuda:0 for local sentence-transformers workloads.
Qwen/Qwen3-0.6B is the fast local generation default. The old Qwen/Qwen3-8B path downloads roughly 16 GB and CPU generation can appear stuck.
If Qwen returns invalid JSON in generative answer mode, the CLI falls back to deterministic evidence rendering instead of failing the answer.
Transformers cache_dir deprecation warnings and Windows Hugging Face symlink warnings are non-fatal and separate from import errors.
For a stuck old local run, try Ctrl+C first. If that fails, use a second PowerShell:
Get-CimInstance Win32_Process | Where-Object CommandLine -match 'multi-agentic-rag|Qwen|hf_reasoning'
Stop only the matching Python or uv process. Do not broadly kill every python.exe.
```

## BRD V1/V2 Full Run

```powershell
uv run --no-sync multi-agentic-rag clean-system-state --system PROJECT_1 --kb default --yes
uv run --no-sync multi-agentic-rag ingest .\documents\BRD_v1.pdf --system PROJECT_1 --version v1 --kb default
uv run --no-sync multi-agentic-rag user-stories --system PROJECT_1 --version v1 --kb default
uv run --no-sync multi-agentic-rag ingest .\documents\BRD_v2.pdf --system PROJECT_1 --version v2 --kb default
uv run --no-sync multi-agentic-rag user-stories --system PROJECT_1 --version v2 --kb default
uv run --no-sync multi-agentic-rag retrieve "what changed in requirements" --system PROJECT_1 --kb default --version v2 --top-k 5 --show-graph-paths
uv run --no-sync multi-agentic-rag ask "What changed in requirements?" --system PROJECT_1 --kb default --version v2
```

Expected lifecycle:

```text
v1 is active after first ingest.
v1 stories are generated from v1 evidence.
v2 supersedes v1 when newer.
Deltas are stored in PostgreSQL.
Superseded Chroma metadata is refreshed.
Neo4j projects the new version and supersession.
v2 stories are generated from v2 evidence.
```

## Validation Commands

Run focused and full validation:

```powershell
uv run --no-sync pytest tests\unit\test_cli_cleanup.py -q
uv run --no-sync pytest -q
uv run --no-sync ruff check .
uv run --no-sync mypy
```

Verify CLI help after command changes:

```powershell
uv run --no-sync multi-agentic-rag health-check
uv run --no-sync multi-agentic-rag clean-system-state --help
uv run --no-sync multi-agentic-rag clean-postgres-state --help
uv run --no-sync multi-agentic-rag clean-chroma-state --help
uv run --no-sync multi-agentic-rag clean-neo4j-state --help
uv run --no-sync multi-agentic-rag hf-check
```

Expected validation shape:

```text
pytest: all selected tests pass
ruff: All checks passed
mypy: Success: no issues found
health-check: PASS rows for PostgreSQL, Chroma, and Neo4j
```

`health-check` depends on live local services and may fail even when code and tests are correct.
