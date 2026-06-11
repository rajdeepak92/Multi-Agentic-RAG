# multi-agentic-rag

`multi-agentic-rag` is a local-first GraphRAG project for version-aware BRD/RAG
analysis. It uses the Option-4 architecture: Knowledge Graph + GraphRAG +
Multi-Agent. The current goal is to ingest BRD V1/V2, preserve old evidence,
mark the latest version active, create deterministic deltas, and support
current, historical, and delta queries.

## 1. Project Quick Setup

1. Open PowerShell.

2. Go to the project:

```powershell
cd "D:\Multi-Agentic-RAG"
```

3. Confirm Python and uv:

```powershell
python --version
uv --version
```

4. Sync dependencies:

```powershell
uv sync
```

5. Copy the environment file if a template exists:

```powershell
copy .env.example .env
```

If `.env.example` is not present, create or edit `.env` directly with the values
shown below.

6. Open `.env`:

```powershell
notepad .env
```

7. Required `.env` values:

```env
OPENAI_API_KEY=<your_key>
HF_TOKEN=<your_token>

NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<your_neo4j_password>

CHROMA_PATH=.multi_agentic_rag/chroma
SQLITE_DB_PATH=.multi_agentic_rag/registry.db
```

8. Start Neo4j Desktop manually:

- Open Neo4j Desktop.
- Start the local DBMS.
- Confirm Neo4j Browser works.
- Run this in Neo4j Browser:

```cypher
RETURN "Neo4j is connected successfully" AS message
```

9. Run doctor:

```powershell
uv run multi-agentic-rag doctor
```

Expected checks:

- Python PASS
- .env PASS
- OPENAI_API_KEY PASS
- HF_TOKEN PASS
- SQLite registry PASS
- ChromaDB PASS
- Neo4j PASS
- FastAPI app PASS

10. Run tests:

```powershell
uv run pytest -c pyproject.toml tests
```

Expected: all project tests pass.

Do not run pytest from `C:\Users\rdmpr`. Always run tests from
`D:\Multi-Agentic-RAG`.

## 2. Project Quick Overview / Purpose

This project is a local-first AI/RAG framework for requirement documents. It is
designed to answer questions like:

- What is the current requirement?
- What changed between BRD V1 and BRD V2?
- Which old requirement was superseded?
- Which requirement needs coverage?
- What evidence supports the answer?

Important scientific rules:

```text
No evidence -> no answer.
No version -> no truth.
No delta -> no impact claim.
No requirement link -> no coverage claim.
```

Version lifecycle:

```text
V1 is ingested first.
V1 becomes active.

V2 is ingested later.
V1 becomes superseded.
V2 becomes active.

Old V1 evidence is preserved.
V2 is used for current truth.
Delta records explain what changed.
Nothing is hard-deleted.
```

Current architecture components:

| Component | Purpose |
| --- | --- |
| Typer CLI | Run local commands |
| FastAPI | Local API boundary |
| SQLite | Stores metadata, document versions, chunks, facts, deltas |
| ChromaDB | Stores local vector index |
| Neo4j | Stores graph nodes and relationships |
| PyMuPDF | Parses PDF text |
| LangGraph | Workflow skeleton for future multi-agent flow |
| LangChain | Helper layer for loaders, splitters, LLM/retrieval integrations |
| MCP folder | Placeholder for future MCP tools/server |

Docker is not used. Neo4j is installed and started locally through Neo4j
Desktop. MCP is planned later and is not active yet.

## 3. Project Walkthrough Step by Step

### Step 1: Validate project

```powershell
cd "D:\Multi-Agentic-RAG"
uv run multi-agentic-rag doctor
uv run pytest -c pyproject.toml tests
```

### Step 2: Verify real BRD files

The real source BRD files are expected at:

```text
D:\Multi-Agentic-RAG\SIIMCS_BRD_V1.pdf
D:\Multi-Agentic-RAG\SIIMCS_BRD_V2.pdf
```

Check:

```powershell
Test-Path ".\SIIMCS_BRD_V1.pdf"
Test-Path ".\SIIMCS_BRD_V2.pdf"
```

Expected:

```text
True
True
```

### Step 3: Validate real BRD files

```powershell
uv run multi-agentic-rag validate-real-brd
```

This checks whether both PDFs exist, whether PyMuPDF can read them, and whether
text can be extracted. It does not ingest anything.

### Step 4: Ingest real BRD files

```powershell
uv run multi-agentic-rag ingest-real-brd
```

Expected behavior:

- Uses `SIIMCS_BRD_V1.pdf` as version `v1`.
- Uses `SIIMCS_BRD_V2.pdf` as version `v2`.
- Copies managed document versions into `.multi_agentic_rag\documents`.
- Keeps original files unchanged.
- Writes metadata into SQLite.
- Writes vectors into ChromaDB.
- Writes graph nodes and edges into Neo4j.
- Marks V1 as superseded.
- Marks V2 as active.
- Generates delta records where deterministic facts changed.

### Step 5: Run graph check

```powershell
uv run multi-agentic-rag graph-check
```

This validates the Neo4j connection. It creates a temporary test node, reads it
back, and deletes only that temporary test node. It does not touch real graph
data.

### Step 6: Run demo workflow

```powershell
uv run multi-agentic-rag demo-pdf
uv run multi-agentic-rag demo-run
```

The demo creates simple V1/V2 PDFs. V1 has threshold `70 C`. V2 has threshold
`80 C`. The demo proves active/superseded/delta behavior.

### Step 7: Query current truth

```powershell
uv run multi-agentic-rag query "What is the current temperature threshold?"
```

Expected behavior:

- Uses active/latest V2 evidence only.
- Does not treat superseded V1 as current truth.

If both demo and real BRD data exist, add `--system SIIMCS_DEMO` or
`--system SIIMCS` to scope the query.

### Step 8: Query delta

```powershell
uv run multi-agentic-rag delta --system SIIMCS --from v1 --to v2
```

Expected: shows deterministic changes between V1 and V2 when extractable.

### Step 9: Generate coverage draft

```powershell
uv run multi-agentic-rag coverage --system SIIMCS
```

Expected: generates early coverage output from active requirement evidence.

### Step 10: Start FastAPI

```powershell
uv run multi-agentic-rag api
```

Open:

```text
http://127.0.0.1:8000/docs
```

Stop with:

```text
Ctrl + C
```

## 4. Current Commands

| Command | Purpose |
| --- | --- |
| `uv run multi-agentic-rag doctor` | Check local setup |
| `uv run pytest -c pyproject.toml tests` | Run safe project tests |
| `uv run multi-agentic-rag graph-check` | Validate Neo4j graph connection |
| `uv run multi-agentic-rag validate-real-brd` | Validate BRD V1/V2 files |
| `uv run multi-agentic-rag ingest-real-brd` | Ingest real BRD V1/V2 files |
| `uv run multi-agentic-rag demo-pdf` | Generate demo V1/V2 PDFs |
| `uv run multi-agentic-rag demo-run` | Run demo ingestion/query/delta workflow |
| `uv run multi-agentic-rag query "<question>"` | Ask current-truth question |
| `uv run multi-agentic-rag delta --system SIIMCS --from v1 --to v2` | Show version delta |
| `uv run multi-agentic-rag coverage --system SIIMCS` | Generate coverage draft |
| `uv run multi-agentic-rag api` | Start FastAPI service |

The optional CLI alias `multi-rag` points to the same Typer app.

## 5. Folder Guide

```text
D:\Multi-Agentic-RAG\
├── SIIMCS_BRD_V1.pdf              # real BRD source input
├── SIIMCS_BRD_V2.pdf              # real BRD source input
├── README.md
├── ARCHITECTURE.md
├── ARCHITECTURE.mermaid
├── pyproject.toml
├── .env
├── .env.example                   # optional template if present
├── src\
│   └── multi_agentic_rag\
├── tests\
├── scripts\
│   └── run_tests.ps1
└── .multi_agentic_rag\
    ├── documents\                 # managed ingested copies
    ├── chroma\                    # ChromaDB local vector data
    ├── exports\
    └── registry.db                # SQLite registry
```

Root BRD PDFs are source files. `.multi_agentic_rag` is app-managed runtime data.
Do not manually edit `.multi_agentic_rag` unless debugging.

## 6. What Has Been Completed

- Local Python package foundation created.
- CLI command created.
- FastAPI app created.
- SQLite registry created.
- ChromaDB local vector store added.
- Neo4j local graph connection verified.
- PDF parsing foundation added.
- Deterministic extraction foundation added.
- Version lifecycle foundation added.
- Delta foundation added.
- Coverage draft foundation added.
- Tests are passing.
- README and architecture docs are maintained.

## 7. What Is Not Done Yet

- Full MCP server is not active yet.
- Full production UI is not built.
- PostgreSQL is not used yet.
- Weaviate is not used yet.
- OpenSearch is not used yet.
- MinIO/S3 is not used yet.
- Full LLM extraction is not complete yet.
- Advanced semantic delta is not complete yet.
- Enterprise deployment is not done yet.

## 8. Important Development Rules

```text
Do not use Docker.
Do not run pytest from C:\Users\rdmpr.
Do not hard-delete old evidence.
Do not overwrite source BRD files.
Use uv run for project commands.
Use 127.0.0.1 for Neo4j URI.
```

## 9. Link to Architecture

For deeper design details, read:

```text
ARCHITECTURE.md
ARCHITECTURE.mermaid
```
