# Multi-Agentic RAG Setup Guide

This is the root-only setup path for `D:\Multi-Agentic-RAG` on Windows PowerShell.
Runtime commands are run from the repository root, use `base_config.json` for non-secret settings, and use `.env` only for secrets.

## 1. Open The Repo

```powershell
cd D:\Multi-Agentic-RAG
```

## 2. Use uv Copy Mode

Use copy mode to avoid hardlink warnings and broken Torch metadata on Windows:

```powershell
$env:UV_LINK_MODE = "copy"
uv sync --dev --link-mode=copy
```

For local Hugging Face reasoning, choose one profile and keep using `uv run --no-sync` afterward:

```powershell
# CPU
uv sync --dev --extra hf-reasoning --extra cpu --link-mode=copy

# NVIDIA CUDA
uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy
```

## 3. Configure Secrets

Create `.env`:

```powershell
Copy-Item .env.example .env
```

Set only secret values:

```env
POSTGRES_DSN=postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>
OPENAI_API_KEY=<your_openai_api_key>
HF_TOKEN=<your_huggingface_token>
GEMINI_API_KEY=<your_gemini_api_key>
NEO4J_PASSWORD=<your_neo4j_password>
```

Do not put plaintext secrets in `base_config.json`. That file stores secret environment variable names such as `POSTGRES_DSN`, `OPENAI_API_KEY`, `HF_TOKEN`, `GEMINI_API_KEY`, and `NEO4J_PASSWORD`.

## 4. Confirm Root Config

`base_config.json` is the single app-owned runtime profile. It sets:

- `paths.cache_dir=.global_cache` and `paths.generated_dir=generated`
- `lexical.backend=pg_textsearch`
- `embeddings.model=BAAI/bge-m3`
- CUDA placement for embeddings, optional reranking, and HF reasoning
- Chroma collection name
- Neo4j URI, username, and database
- PostgreSQL timeout/pool settings

Initialize it only if it is missing:

```powershell
uv run --no-sync multi-agentic-rag init .
```

Normal commands should not rewrite `base_config.json`.

## 5. Apply Database Migrations

Run Alembic against the same `POSTGRES_DSN` used by the CLI:

```powershell
uv run --no-sync alembic current
uv run --no-sync alembic heads
uv run --no-sync alembic upgrade head
```

For the current BM25 path, head must include `20260620_0004`. Verify the target database:

```sql
SELECT version_num FROM alembic_version;
SELECT extname FROM pg_extension WHERE extname = 'pg_textsearch';
SELECT to_regclass('idx_chunks_text_bm25');
```

If `current=20260620_0003, head=20260620_0004`, the database is behind. Run:

```powershell
uv run --no-sync alembic upgrade head
```

If `pg_textsearch` is missing, the server/database does not support the canonical BM25 path. Keep `pg_textsearch` for Tiger/PostgreSQL targets that support it. Use `BM25_BACKEND=postgres_fts` only as an explicit non-BM25 fallback for a local database.

If Alembic reports no current revision or `idx_chunks_text_bm25` is missing while the expected database was already migrated, verify that `.env` points `POSTGRES_DSN` at the same database used by the CLI.

## 6. Verify Runtime

```powershell
uv run --no-sync multi-agentic-rag --help
uv run --no-sync qa-doctor
uv run --no-sync multi-agentic-rag health-check
uv run --no-sync multi-agentic-rag hf-check
```

`qa-doctor` reports the root `base_config.json`, redacted database target, Alembic revision, `pg_textsearch` extension, BM25 index, Chroma, Neo4j, provider keys, Torch, CUDA, and uv link-mode guidance.

## 7. Ingest And Query

Put source documents under `documents\`:

```text
documents\PROJECT_1_BRD_v1.md
```

Ingest with the root wrapper:

```powershell
uv run --no-sync qa-ingest .\documents\PROJECT_1_BRD_v1.md --system PROJECT_1 --version v1 --model hf
```

Ask and inspect retrieval:

```powershell
uv run --no-sync multi-agentic-rag ask "What is the temperature threshold?" --system PROJECT_1 --kb default --version v1 --model hf
uv run --no-sync multi-agentic-rag retrieve "temperature threshold" --system PROJECT_1 --kb default --version v1 --top-k 5 --show-graph-paths
```

Generate user stories:

```powershell
uv run --no-sync qa-user-stories --system PROJECT_1 --version v1 --model hf
```

Run artifacts are written under:

```text
generated\RUN_YYYYMMDD_HHMMSS_<shortid>\
  logs\run.log
  run_manifest.json
  results\
    artifacts\user_stories\
    debug\
```

## 8. Cleanup

Clean one scoped system:

```powershell
uv run --no-sync multi-agentic-rag clean-system-state --system PROJECT_1 --kb default --yes
```

Clean root run artifacts:

```powershell
Remove-Item -Recurse -Force .\generated
New-Item -ItemType Directory .\generated
```

Clean root app cache:

```powershell
Remove-Item -Recurse -Force .\.global_cache
```

Repair a confused `.venv` after CPU/GPU extra switching:

```powershell
deactivate
Remove-Item -Recurse -Force .\.venv
uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy
```

## 9. Common Failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Failed to hardlink files; falling back to full copy` | uv hardlink mode is not reliable on this machine. | Use `UV_LINK_MODE=copy` or `uv sync --link-mode=copy`. |
| CUDA worked, then `torch` becomes CPU-only | A plain `uv run` resynced without GPU extras. | Run the chosen `uv sync --extra ... --link-mode=copy` again, then use `uv run --no-sync`. |
| `pg_textsearch extension is not available` | The target DB lacks the canonical BM25 extension. | Use a DB that supports `pg_textsearch`, or explicitly choose `BM25_BACKEND=postgres_fts` for local fallback. |
| `current=20260620_0003, head=20260620_0004` | Alembic migrations are behind head. | Run `uv run --no-sync alembic upgrade head` against the CLI `POSTGRES_DSN`. |
| `idx_chunks_text_bm25` missing | Migration `20260620_0004` was not applied to this database, or the DSN is wrong. | Verify `.env` and rerun `uv run --no-sync alembic upgrade head`. |
| `No module named pip` inside `.venv` | uv environments do not need pip by default. | Use `uv pip list`, `uv sync`, and `uv run`. |

## 10. Final Validation

```powershell
uv run --no-sync ruff check
uv run --no-sync pytest -m "not tiger_cloud and not gpu"
git diff --check
```
