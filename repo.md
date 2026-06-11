# Fresh Clone Setup Guide

This file explains what to do after cloning this repository from GitHub so the
`multi-agentic-rag` framework can be installed, validated, and started.

## 1. Prerequisites

Install or verify these first:

- Python 3.12 or newer
- uv
- PowerShell
- Neo4j Desktop, if you want graph indexing and graph-aware workflows
- OpenAI API key, recommended for LLM-backed features
- Hugging Face token, recommended for model downloads

Check Python and uv:

```powershell
python --version
uv --version
```

## 2. Clone The Repository

```powershell
git clone <repo-url>
cd <repo-folder>
```

From this point, run commands from the repository root. Do not run project
commands from another directory.

## 3. Install Dependencies

```powershell
uv sync
```

This creates the local virtual environment and installs the package
dependencies from `pyproject.toml` and `uv.lock`.

## 4. Create The Environment File

The `.env` file is intentionally ignored by git, so create it after cloning.

If the repo has a template:

```powershell
copy .env.example .env
```

If no template exists, create `.env` manually:

```powershell
notepad .env
```

Use this as the starting configuration:

```env
OPENAI_API_KEY=<your_openai_api_key>
HF_TOKEN=<your_huggingface_token>

HF_HOME=.cache/huggingface
HF_HUB_CACHE=.cache/huggingface/hub

MULTI_AGENTIC_RAG_HOME=.multi_agentic_rag
MULTI_AGENTIC_RAG_PROFILE=local

NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<your_neo4j_password>

CHROMA_PATH=.multi_agentic_rag/chroma
SQLITE_DB_PATH=.multi_agentic_rag/registry.db

DEFAULT_EMBEDDING_MODEL=BAAI/bge-m3
DEFAULT_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
DEFAULT_LLM_MODEL=gpt-5.5

API_HOST=127.0.0.1
API_PORT=8000

MCP_ENABLED=false
MCP_TRANSPORT=stdio
```

Optional values for `scripts/start-neo4j-desktop.ps1`:

```env
NEO4J_DESKTOP_EXE=<path_to_neo4j_desktop_exe>
NEO4J_DESKTOP_DATA_PATH=neo4j/desktop-data
NEO4J_DUMPS_DIR=neo4j/dumps
NEO4J_IMPORT_DIR=neo4j/import
```

## 5. Initialize Local Runtime State

```powershell
uv run multi-agentic-rag init
```

This creates local runtime folders and initializes the SQLite registry. Runtime
state is stored under `.multi_agentic_rag/` and is ignored by git.

## 6. Start Neo4j

Start Neo4j Desktop manually and start the local DBMS that matches the
credentials in `.env`.

In Neo4j Browser, verify the connection:

```cypher
RETURN "Neo4j is connected successfully" AS message
```

You can also use the helper script if the optional Neo4j Desktop environment
variables are configured:

```powershell
.\scripts\start-neo4j-desktop.ps1
```

## 7. Validate The Local Setup

Run the project diagnostics:

```powershell
uv run multi-agentic-rag doctor
```

Expected important checks:

- Python passes
- `.env` is found
- SQLite registry passes
- ChromaDB passes
- Neo4j passes or warns if Neo4j is not running
- FastAPI app imports

Run tests from the repo root:

```powershell
uv run pytest -c pyproject.toml tests
```

Or use the helper script:

```powershell
.\scripts\run_tests.ps1
```

## 8. Choose A Data Path

### Option A: Use The Included Real BRD PDFs

Verify the source PDFs exist:

```powershell
Test-Path ".\SIIMCS_BRD_V1.pdf"
Test-Path ".\SIIMCS_BRD_V2.pdf"
```

Validate them without ingesting:

```powershell
uv run multi-agentic-rag validate-real-brd
```

Ingest V1 and V2 in version order:

```powershell
uv run multi-agentic-rag ingest-real-brd
```

This copies managed document versions into `.multi_agentic_rag/documents`,
writes metadata to SQLite, writes vectors to ChromaDB, writes graph data to
Neo4j when available, marks V1 as superseded, marks V2 as active, and creates
deterministic delta records where changes are found.

### Option B: Use The Demo Workflow

Generate deterministic demo PDFs:

```powershell
uv run multi-agentic-rag demo-pdf
```

Run the demo ingestion, query, delta, and coverage workflow:

```powershell
uv run multi-agentic-rag demo-run
```

## 9. Run Framework Commands

Query current evidence:

```powershell
uv run multi-agentic-rag query "What is the current temperature threshold?"
```

Scope queries when both demo and real BRD data exist:

```powershell
uv run multi-agentic-rag query "What changed between V1 and V2?" --system SIIMCS
```

Show deltas:

```powershell
uv run multi-agentic-rag delta --system SIIMCS --from v1 --to v2
```

Generate a coverage draft:

```powershell
uv run multi-agentic-rag coverage --system SIIMCS
```

Check Neo4j read/write/delete behavior:

```powershell
uv run multi-agentic-rag graph-check
```

## 10. Start The API

```powershell
uv run multi-agentic-rag api
```

Open these URLs:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/doctor
http://127.0.0.1:8000/docs
```

Stop the API with:

```text
Ctrl + C
```

## 11. Useful Commands

```powershell
uv run multi-agentic-rag --help
uv run multi-agentic-rag doctor
uv run multi-agentic-rag init
uv run multi-agentic-rag validate-real-brd
uv run multi-agentic-rag ingest-real-brd
uv run multi-agentic-rag demo-pdf
uv run multi-agentic-rag demo-run
uv run multi-agentic-rag query "<question>"
uv run multi-agentic-rag delta --system SIIMCS --from v1 --to v2
uv run multi-agentic-rag coverage --system SIIMCS
uv run multi-agentic-rag graph-check
uv run multi-agentic-rag api
```

The shorter alias also points to the same CLI:

```powershell
uv run multi-rag --help
```

## 12. Local Files To Know

- `.env`: local secrets and runtime configuration, ignored by git
- `.multi_agentic_rag/`: app-managed runtime state, ignored by git
- `.cache/`: local Hugging Face/model cache, ignored by git
- `neo4j/`: local Neo4j helper data, ignored by git
- `SIIMCS_BRD_V1.pdf` and `SIIMCS_BRD_V2.pdf`: real source BRD inputs
- `ARCHITECTURE.md`: architecture details
- `ARCHITECTURE.mermaid`: architecture diagram source

Do not manually edit `.multi_agentic_rag/` unless debugging local state.

