# Setup

This project runs locally by default with SQLite, ChromaDB, and Neo4j.

## 1. Create a virtual environment

```powershell
uv venv .venv
.venv\Scripts\Activate.ps1
uv sync --locked
```

## 2. Configure local runtime values

Copy `.env.example` to `.env` and set the Neo4j password plus the helper paths for your local Neo4j Desktop install.

Required local values:

```env
NEO4J_PASSWORD=your-local-password
NEO4J_DBMS_HOME=...
NEO4J_JAVA_HOME=...
```

## 3. Initialize the workspace

```powershell
uv run multi-agentic-rag init
```

This creates the local runtime directories and initializes the configured SQLite registry.

## 4. Start local Neo4j

Use the helper script after Neo4j Desktop is installed:

```powershell
.\scripts\start-neo4j-desktop.ps1
```

If your Neo4j paths are correct, the script waits for Bolt and Browser ports, runs `graph-check`, and leaves Neo4j running in a hidden console window.

## 5. Verify the runtime

```powershell
uv run multi-agentic-rag doctor --system PROJECT_1 --version v1
uv run multi-agentic-rag graph-check
```

## 6. Ingest documents

```powershell
uv run multi-agentic-rag ingest documents/inbox/PROJECT_1/SIIMCS_BRD_V1.pdf --system PROJECT_1 --version v1
uv run multi-agentic-rag ingest documents/inbox/PROJECT_1/SIIMCS_BRD_V2.pdf --system PROJECT_1 --version v2
```

## 6. What to expect

- SQLite stores document metadata, chunk rows, facts, deltas, coverage records, and execution results.
- ChromaDB stores local chunk vectors and search metadata.
- Neo4j stores document lineage, chunk evidence links, and graph-backed requirement relationships.
- V2 ingestion supersedes V1 when the same system is ingested again with a later version.
