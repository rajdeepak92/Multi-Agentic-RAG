# multi-agentic-rag

`multi-agentic-rag` is a local-first Multi-Agentic RAG framework for
version-aware engineering documents. It ingests BRD/SRS/design files, preserves
evidence by document version, retrieves through graph/vector/keyword stores, and
currently generates dummy automation-style pytest testcases from requirement
evidence.

The project is built around these rules:

```text
No evidence -> no answer.
No version -> no truth.
No delta -> no impact claim.
No requirement link -> no coverage claim.
```

Docker is not part of the local workflow. The current runtime uses Python,
SQLite, a filesystem object store, SQLite FTS5/BM25, ChromaDB fallback vectors,
optional Weaviate, and optional Neo4j Desktop.

## Current Behavior

Built today:

- Document ingestion from PDF/DOCX into chunks, facts, SQLite, BM25, object
  artifacts, vectors, and optional Neo4j.
- Version lifecycle where newer documents supersede older active documents
  without deleting old evidence.
- Evidence-based query, delta, and coverage commands.
- Coverage planning that requires requirement-linked evidence and stores a
  reusable `coverage_run`.
- Dummy pytest automation generation under `generated/<system>/<brd_version>/`.
- Sidecar testcase JSON that tracks scenarios, source chunks, expected values,
  dependency audit, workflow handoff, retry policy, and run history.
- Test execution through pytest with generated `pytest.ini`, `conftest.py`,
  fixtures, markers, hooks, logging, syntax validation, and stored results.
- CLI and FastAPI routes for ingestion, query, coverage, task routing, test
  generation, test execution, and last-result lookup.

Not built yet:

- Production UI/auth.
- Full MCP server.
- PostgreSQL/OpenSearch/MinIO production backends.
- Real device/protocol interface automation.
- Fully compiled LangGraph subgraphs for every agent handoff.
- LLM-backed extraction and final answer generation beyond conservative
  evidence assembly.

## Clean Windows Setup

Install these on a clean Windows machine:

- Python 3.12 or newer.
- `uv`.
- PowerShell.
- Neo4j Desktop, optional but recommended for graph-check and graph retrieval.
- Tesseract OCR, optional and only needed for scanned PDFs.
- OpenAI/Azure OpenAI/HuggingFace tokens, optional for later LLM or HF-backed
  model usage. The current dummy automation path can run with local hashing.

From PowerShell:

```powershell
cd "D:\Multi-Agentic-RAG"
python --version
uv --version
uv venv .venv --prompt Multi-Agentic-RAG
.\.venv\Scripts\Activate.ps1
uv sync --locked
copy .env.example .env
notepad .env
```

If you intentionally changed `pyproject.toml`, run `uv sync` so `uv.lock` is
updated. For normal fresh-clone setup, prefer `uv sync --locked` so dependency
resolution matches the committed lock file.

This project does not require `requirements.txt`. Dependencies are declared in
`pyproject.toml` and locked in `uv.lock`. Do not create a separate
`requirements.txt` unless you are exporting one for another tool.

Initialize and validate:

```powershell
uv run multi-agentic-rag init
uv run multi-agentic-rag doctor
uv run pytest -c pyproject.toml tests
```

Run commands from the repository root, not from `C:\Users\<you>`.

## Required Folder Structure

Create the source inbox before ingestion:

```text
D:\Multi-Agentic-RAG\
|-- documents\
|   `-- inbox\
|       `-- PROJECT_1\
|           |-- SIIMCS_BRD_V1.pdf
|           `-- SIIMCS_BRD_V2.pdf
|-- neo4j\
|   |-- dumps\        # optional local Neo4j dumps, ignored
|   `-- import\       # optional local Neo4j import files, ignored
|-- .env
|-- .env.example
|-- pyproject.toml
|-- uv.lock
|-- src\
`-- tests\
```

MARAG creates these runtime folders as needed:

```text
.multi_agentic_rag/
  documents/       # managed source copies
  objects/         # parsed JSONL artifacts
  chroma/          # Chroma fallback vectors
  exports/
  registry.db      # SQLite metadata, FTS5, coverage, and test result records

generated/
  project_1/
    brd_v1/
      test_project_1_brd_v1.py
      test_project_1_brd_v1.json
      conftest.py
      pytest.ini
```

Do not manually edit `.multi_agentic_rag` unless debugging runtime state.

## Environment Values

`.env` is local and ignored by git. Start from `.env.example`, then set values
for your machine.

Minimum local values:

```env
MULTI_AGENTIC_RAG_HOME=.multi_agentic_rag
MULTI_AGENTIC_RAG_PROFILE=local
SQLITE_DB_PATH=.multi_agentic_rag/registry.db
OBJECT_STORE_PATH=.multi_agentic_rag/objects

VECTOR_STORE_PROVIDER=auto
WEAVIATE_URL=
WEAVIATE_API_KEY=
WEAVIATE_COLLECTION=MultiAgenticRagChunk
WEAVIATE_HYBRID_ALPHA=0.65
CHROMA_PATH=.multi_agentic_rag/chroma
KEYWORD_INDEX_ENABLED=true

EMBEDDING_PROVIDER=hash
DEFAULT_EMBEDDING_MODEL=BAAI/bge-m3
DEFAULT_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
HF_TOKEN=
HF_HOME=.cache/huggingface
HF_HUB_CACHE=.cache/huggingface/hub

LLM_PROVIDER=none
DEFAULT_LLM_MODEL=gpt-5.5
OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_DEPLOYMENT=

ENABLE_PDF_OCR=false
TESSERACT_CMD=

API_HOST=127.0.0.1
API_PORT=8000
MCP_ENABLED=false
MCP_TRANSPORT=stdio
```

Use `EMBEDDING_PROVIDER=hash` for deterministic local runs without HuggingFace
model downloads. Use `EMBEDDING_PROVIDER=huggingface` only after local model
download/cache behavior is acceptable for your machine.

## Neo4j Desktop Setup

Neo4j is optional for dummy testcase generation, but required for graph-check and
graph retrieval.

1. Install Neo4j Desktop.
2. Create a local DBMS.
3. Set and remember the DBMS password.
4. Start the DBMS.
5. Confirm Browser runs on `http://127.0.0.1:7474` and Bolt on
   `bolt://127.0.0.1:7687`.
6. Put the matching values in `.env`:

```env
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<your_neo4j_password>
NEO4J_DATABASE=neo4j
NEO4J_HOST=127.0.0.1
NEO4J_BOLT_PORT=7687
NEO4J_BROWSER_PORT=7474
```

Optional helper-script values:

```env
NEO4J_DESKTOP_EXE=
NEO4J_DESKTOP_DATA_PATH=
NEO4J_DBMS_HOME=
NEO4J_JAVA_HOME=
NEO4J_DUMPS_DIR=neo4j/dumps
NEO4J_IMPORT_DIR=neo4j/import
```

After Neo4j is running:

```powershell
uv run multi-agentic-rag graph-check
```

## Gitignore Contract

The repo ignores local-only artifacts:

- `.env` for secrets and machine-specific paths.
- `.venv/` for the local Python environment.
- `.multi_agentic_rag/` for SQLite, parsed objects, managed document copies,
  Chroma vectors, and exports.
- `.cache/` for local model/package caches.
- `generated/` for MARAG generated pytest and JSON testcase artifacts.
- `tests/generated/` for the older generated-test location.
- `neo4j/runtime/`, `neo4j/dumps/`, `neo4j/import/`, and
  `neo4j-desktop-data/` for local Neo4j data.
- Python build/test caches and ad hoc local `*.db`, `*.sqlite`, and `*.log`
  files.

The `documents/inbox/PROJECT_1/` folder is not ignored by default because this
repo currently uses dummy BRD files as reproducible local inputs.

## Happy Path

Use the exact flow below for the current PROJECT_1 BRD example:

```powershell
uv sync --locked
uv run multi-agentic-rag ingest-folder "documents\inbox\PROJECT_1" --system PROJECT_1 --version v1
uv run multi-agentic-rag coverage-plan --system PROJECT_1 --version v1 --count 10
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 10
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 10
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 5
```

Expected shape after ingestion:

```text
Folder Ingestion
File              Status  Chunks  Facts
SIIMCS_BRD_V1.pdf active  14      77
SIIMCS_BRD_V2.pdf active  20      104
```

Expected generated artifact path:

```text
generated\project_1\brd_v1\test_project_1_brd_v1.py
generated\project_1\brd_v1\test_project_1_brd_v1.json
generated\project_1\brd_v1\conftest.py
generated\project_1\brd_v1\pytest.ini
```

Expected testcase result shape:

```text
executed: Test run passed: 10 passed, 0 failed, 0 skipped.
```

The tests are placeholder automation tests. They use evidence-derived
`expected_values`, log at `DEBUG`, `WARNING`, and `INFO`, and return `True`
after traceability checks pass. They do not call real MQTT, REST, CAN, Modbus,
device, or application interfaces yet.

## Test Automation Flow

For testcase generation, the current service flow is:

```text
IntentRouter
-> DocumentResolver
-> EvidenceCollector
-> ScenarioSelector
-> TestPlanAgent
-> DependencyAuditAgent
-> HarnessAgent
-> TestCodeWriterAgent
-> PytestValidationAgent
-> ExecutionAgent
-> FailureDebuggerAgent
-> TrackingJsonAgent
-> DbUpdateAgent
```

Today this handoff is recorded in JSON and implemented as deterministic Python
services. A later LangGraph orchestration layer can reuse the same state
contract.

The retry policy is controlled:

```text
generate -> validate syntax -> run pytest -> classify failure
-> regenerate only for fixable generated-code failures -> retry up to 5
```

Missing modules, refused connections, timeouts, and unavailable services are
recorded as environment blockers instead of blindly rewriting tests.

## CLI Commands

| Command | Purpose |
| --- | --- |
| `uv run multi-agentic-rag init` | Create local runtime folders and SQLite registry |
| `uv run multi-agentic-rag doctor` | Check local config and optional services |
| `uv run multi-agentic-rag ingest-doc <path> --system PROJECT_1 --version v1` | Ingest one PDF/DOCX |
| `uv run multi-agentic-rag ingest-folder <folder> --system PROJECT_1 --version v1` | Ingest all PDF/DOCX files in a folder |
| `uv run multi-agentic-rag query "<question>" --system PROJECT_1 --version v1` | Ask evidence-based questions |
| `uv run multi-agentic-rag delta --system PROJECT_1 --from v1 --to v2` | Show deterministic version deltas |
| `uv run multi-agentic-rag coverage --system PROJECT_1 --version v1` | Show coverage records |
| `uv run multi-agentic-rag coverage-plan --system PROJECT_1 --version v1 --count 10` | Generate or reuse scenario coverage |
| `uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 10` | Generate or reuse pytest automation artifacts |
| `uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 10` | Execute generated pytest tests and store result |
| `uv run multi-agentic-rag last-results --system PROJECT_1 --version v1` | Read the latest stored test result without rerunning |
| `uv run multi-agentic-rag task "<request>" --system PROJECT_1 --version v1` | Route a natural-language task |
| `uv run multi-agentic-rag graph-check` | Validate Neo4j read/write/delete behavior |
| `uv run multi-agentic-rag api` | Start FastAPI |
| `uv run multi-agentic-rag mcp-info` | Show the planned MCP boundary |

`multi-rag` is an alias for the same CLI app.

## API

Start FastAPI:

```powershell
uv run multi-agentic-rag api
```

Open:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/doctor
http://127.0.0.1:8000/docs
```

Current endpoints:

- `GET /health`
- `GET /doctor`
- `POST /documents/ingest`
- `POST /query`
- `POST /delta`
- `POST /coverage`
- `POST /coverage/plan`
- `POST /tasks`
- `POST /tests/generate`
- `POST /tests/run`
- `POST /tests/last-result`

## Documentation Map

- `execution.md` explains the current execution behavior step by step.
- `behavior.md` summarizes the current achieved behavior and limits.
- `ARCHITECTURE.md` describes the system boundaries and workflow design.
- `ARCHITECTURE.mermaid` contains the visual architecture diagram.

## Conclusion

MARAG is currently a local-first evidence system plus a document-grounded dummy
test automation generator. The important achievement is traceability: generated
tests do not invent expected values, and successful execution is tied back to
requirements, chunks, versions, JSON run history, and SQLite records. Real
interfaces and LLM-heavy orchestration can be added later on top of this
contract without weakening the evidence rules.
