# Multi-Agentic RAG

GraphRAG-only knowledge base ingestion and retrieval for versioned engineering documents.

This project turns PDF, DOCX, TXT, and Markdown requirement documents into a queryable
knowledge base backed by PostgreSQL, ChromaDB, and Neo4j. The current runtime is focused on
document storage, version lineage, deterministic fact extraction, deltas, graph projection, and
hybrid retrieval. QA automation, generated tests, FastAPI, MCP, LangGraph routing, SQLite, and
Weaviate are intentionally outside the current scope.

## Quick Setup

Run these commands after cloning the repository.

```powershell
cd D:\Multi-Agentic-RAG
uv sync --dev
Copy-Item .env.example .env
```

Edit `.env` before running migrations. At minimum, set PostgreSQL and Neo4j credentials that
match services running on your machine or network.

```powershell
uv run alembic upgrade head
uv run multi-agentic-rag health-check
```

Ingest a first document:

```powershell
uv run multi-agentic-rag ingest documents\PROJECT_1_BRD_v1.md --system PROJECT_1 --version v1 --kb default
```

Retrieve evidence:

```powershell
uv run multi-agentic-rag retrieve "temperature threshold" --system PROJECT_1 --kb default --top-k 5
```

## Environment Setup

The project does not start infrastructure for you. Install and start the services manually.

### Python And Dependencies

- Python: `>=3.12`
- Package manager: `uv`
- Dev validation: `pytest`, `ruff`, and `mypy` are installed by `uv sync --dev`

Useful commands:

```powershell
uv sync --dev
uv run pytest -q
uv run ruff check .
uv run mypy src/multi_agentic_rag
```

### PostgreSQL 16+

PostgreSQL is the authoritative metadata store and BM25/full-text retrieval backend.

Manual setup checklist:

1. Install PostgreSQL 16 or newer.
2. Create a database and user for this app.
3. Confirm the database accepts TCP connections.
4. Put the async SQLAlchemy DSN in `.env`.
5. Run Alembic migrations.

Example `.env` value:

```env
POSTGRES_DSN=postgresql+asyncpg://marag:marag@127.0.0.1:5432/marag
```

Example readiness commands:

```powershell
uv run alembic upgrade head
uv run multi-agentic-rag db-check
```

If `alembic upgrade head` fails with `POSTGRES_DSN is required`, `.env` is missing the DSN or
the shell environment does not expose it.

### Neo4j

Neo4j stores the graph projection used by GraphRAG traversal.

Manual setup checklist:

1. Install or provision Neo4j.
2. Start the Neo4j DBMS.
3. Confirm Bolt is reachable.
4. Put URI, username, password, and database in `.env`.
5. Run `graph-check`.

Example `.env` values:

```env
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j
GRAPHRAG_REQUIRED=true
```

Readiness command:

```powershell
uv run multi-agentic-rag graph-check
```

When `GRAPHRAG_REQUIRED=true`, ingestion fails if Neo4j cannot be reached or graph projection
fails after PostgreSQL run state is created.

### ChromaDB

ChromaDB is used as a persistent local vector index by default.

Example `.env` values:

```env
CHROMA_PATH=.multi_agentic_rag/chroma
CHROMA_COLLECTION=multi_agentic_rag_chunks
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIMENSIONS=1024
```

Readiness command:

```powershell
uv run multi-agentic-rag chroma-check
```

`BAAI/bge-m3` is the default semantic embedding model. The first Chroma operation that embeds
documents or queries may download the model through `sentence-transformers`.

Use `EMBEDDING_PROVIDER=hash` only for deterministic offline tests or smoke checks. Hash
embeddings are stable but not semantic, so they should not be used for real retrieval quality.

## Current Agent Purpose

The current agent is `KnowledgeBaseStoringAgent`. Its purpose is to ingest a versioned
document into a durable GraphRAG knowledge base with explicit lineage and retrieval signals.

It is not a general chatbot, test generator, API server, or workflow router. It is the storage
and indexing core that future user-facing tools can safely build on.

### Architecture

```mermaid
flowchart LR
    CLI[Typer CLI] --> Agent[KnowledgeBaseStoringAgent]
    Agent --> Resolve[Resolve + Version Guard]
    Agent --> Parse[Parse PDF/DOCX/TXT/MD]
    Agent --> Chunk[Chunk + Manifest]
    Agent --> Extract[Rule Fact Extraction]
    Agent --> Delta[Version Delta Analysis]
    Agent --> PG[(PostgreSQL 16+)]
    Agent --> Chroma[(ChromaDB)]
    Agent --> Neo4j[(Neo4j)]
    PG --> BM25[BM25 / Full Text]
    Chroma --> Vector[Vector Retriever]
    Neo4j --> Graph[Graph Retriever]
    BM25 --> Hybrid[HybridKnowledgeRetriever]
    Vector --> Hybrid
    Graph --> Hybrid
    Hybrid --> Results[Ranked RetrievalResult Evidence]
```

Main layers:

- `agents/`: orchestration and dependency-injected sub-agents.
- `domain/`: typed DTOs and persisted record contracts.
- `ingestion/`: parsing, version validation, source copy, chunking, and manifests.
- `extraction/`: deterministic rule extraction for requirements, thresholds, protocols, sensors, devices, and topics.
- `delta/`: added, removed, modified, and unchanged fact deltas.
- `infrastructure/postgres/`: async SQLAlchemy repository and ORM models.
- `infrastructure/chroma/`: vector repository.
- `infrastructure/neo4j/`: graph projection and traversal repository.
- `retrieval/`: BM25, vector, graph, hybrid fusion, and reranking interfaces.
- `config/`: Pydantic settings, runtime paths, and structured logging.

## GraphRAG Workflow

The ingestion workflow keeps storage, vector indexing, and graph projection aligned.

### Mandatory Ingestion Contract

Every successful `multi-agentic-rag ingest ...` run must complete all of these steps:

- Parse the source document and create deterministic chunks.
- Extract at least one grounded fact from the chunks.
- Persist the document, version, chunks, facts, deltas, and run state in PostgreSQL.
- Build BGE-M3 embeddings and index every chunk in ChromaDB.
- Project the document/version/chunk/fact graph into Neo4j.
- Verify PostgreSQL BM25/full-text readiness.

If PostgreSQL, ChromaDB, Neo4j, chunking, fact extraction, embedding generation, or graph
projection fails, ingestion fails. The runtime does not treat ChromaDB or Neo4j as optional
stores for a successful GraphRAG ingest.

```mermaid
sequenceDiagram
    participant U as User / CLI
    participant A as KnowledgeBaseStoringAgent
    participant P as Parser
    participant X as Extractor
    participant DB as PostgreSQL
    participant V as ChromaDB
    participant G as Neo4j

    U->>A: ingest(path, system, version, kb)
    A->>A: resolve path, validate version, hash source
    A->>DB: create ingestion_run(started)
    A->>P: parse PDF/DOCX/TXT/MD
    P-->>A: page text
    A->>A: chunk with overlap and write JSONL manifest
    A->>X: extract deterministic facts
    A->>DB: load active previous version and facts
    A->>A: compute added/removed/modified/unchanged deltas
    A->>DB: persist system, document, version, chunks, facts, deltas
    A->>V: upsert chunk vectors and metadata
    A->>G: MERGE graph projection
    A->>DB: verify FTS/BM25 readiness
    A->>DB: mark ingestion_run(succeeded)
    A-->>U: IDs, counts, service statuses
```

Retrieval workflow:

```mermaid
flowchart TD
    Query[Query Text] --> B[PostgreSQL BM25 Retriever]
    Query --> V[Chroma Vector Retriever]
    Query --> G[Neo4j Graph Retriever]
    B --> F[RRF Fusion + Deduplication]
    V --> F
    G --> F
    F --> R[Optional Reranking]
    R --> E[Evidence Chunks With Scores + Sources]
```

Ingestion returns:

- `document_id`
- `document_version_id`
- `chunks_count`
- `facts_count`
- `deltas_count`
- `postgres_status`
- `chroma_status`
- `neo4j_status`
- `bm25_status`
- `ingestion_run_id`

## Current Capabilities

- Ingest PDF, DOCX, TXT, Markdown, and Markdown-like requirement documents.
- Validate filename version hints such as `v1` and `v2`.
- Compute SHA-256 content lineage.
- Copy source documents into managed runtime storage.
- Parse PDF text and tables, DOCX paragraphs and tables, and text/Markdown content.
- Chunk documents deterministically with configurable size and overlap.
- Write JSONL chunk manifests.
- Extract deterministic facts for requirements, thresholds, protocols, protocol details, sensors, devices, and MQTT topics.
- Compare newer versions against the active previous version.
- Store `added`, `removed`, `modified`, and `unchanged` deltas.
- Persist authoritative metadata in PostgreSQL through async SQLAlchemy sessions.
- Use PostgreSQL full-text search as the BM25 backend.
- Index vectors in ChromaDB.
- Project GraphRAG nodes and relationships into Neo4j.
- Retrieve with BM25, vector search, graph expansion, deterministic reciprocal-rank fusion, and optional reranking.

## Use Cases And Advantages

Use cases:

- Build a versioned requirements knowledge base.
- Ask evidence-grounded questions over active engineering documents.
- Compare BRD/SRS versions and inspect changed facts.
- Trace requirements to chunks and source pages.
- Prepare a durable backend for future chat, review, or automation surfaces.

Advantages:

- PostgreSQL is the system of record, so metadata and retrieval state are auditable.
- Neo4j keeps graph traversal separate from row storage.
- Chroma keeps semantic retrieval separate from authoritative metadata.
- Deterministic IDs make re-ingestion and test assertions stable.
- Version deltas prevent silent overwrites of prior evidence.
- External services are behind narrow repository interfaces, making future replacement easier.

## Future Challenges

Be ready for these areas before production use:

- Service operations: backups, credentials, TLS, connection pooling, and health monitoring.
- Migration discipline: schema changes must go through Alembic and compatibility tests.
- Parser fidelity: scanned PDFs need OCR configuration and quality checks.
- Extraction coverage: rule extractors are deterministic but will miss domain facts outside known patterns.
- Graph growth: Neo4j constraints and merge performance need monitoring as documents scale.
- Vector quality: `BAAI/bge-m3` is the semantic default; hash embeddings are only a deterministic offline fallback.
- Reranking cost: cross-encoder reranking improves quality but adds latency and model hosting requirements.
- Access control: document-level authorization is not implemented in the current CLI runtime.
- Conflict handling: concurrent ingestion of the same system/version needs operational policy beyond optimistic version fields.

## Look For What And Where

| Need | Location |
| --- | --- |
| CLI commands | `src/multi_agentic_rag/cli.py` |
| Top-level ingestion agent | `src/multi_agentic_rag/agents/knowledge_base.py` |
| Sub-agent contracts | `src/multi_agentic_rag/agents/sub_agents.py` |
| Domain DTOs | `src/multi_agentic_rag/domain/models.py` |
| Settings and `.env` keys | `src/multi_agentic_rag/config/settings.py`, `.env.example` |
| Parser support | `src/multi_agentic_rag/ingestion/parser.py` |
| Chunking | `src/multi_agentic_rag/ingestion/chunker.py` |
| Source lineage | `src/multi_agentic_rag/ingestion/lineage.py` |
| Fact extraction | `src/multi_agentic_rag/extraction/rule_extractors.py` |
| Delta logic | `src/multi_agentic_rag/delta/differ.py` |
| PostgreSQL schema | `migrations/versions/20260618_0001_initial_graphrag_schema.py` |
| PostgreSQL repository | `src/multi_agentic_rag/infrastructure/postgres/repository.py` |
| Chroma repository | `src/multi_agentic_rag/infrastructure/chroma/repository.py` |
| Neo4j repository | `src/multi_agentic_rag/infrastructure/neo4j/repository.py` |
| Hybrid retrieval | `src/multi_agentic_rag/retrieval/hybrid.py` |
| Architecture docs | `docs/ARCHITECTURE.md` |
| Ingestion flow docs | `docs/INGESTION_FLOW.md` |
| Graph schema docs | `docs/GRAPH_SCHEMA.md` |
| Retrieval docs | `docs/RETRIEVAL_ARCHITECTURE.md` |
| Migration guide | `docs/MIGRATION_GUIDE.md` |

## Visibility Matrix

| Area | Command Or File | Expected Signal |
| --- | --- | --- |
| Dependency installation | `uv sync --dev` | Installs runtime and dev dependencies |
| PostgreSQL readiness | `uv run multi-agentic-rag db-check` | Connection and FTS readiness |
| Schema readiness | `uv run alembic upgrade head` | Database at latest migration |
| Chroma readiness | `uv run multi-agentic-rag chroma-check` | Collection can be opened or created |
| Neo4j readiness | `uv run multi-agentic-rag graph-check` | Temporary graph node can be created, read, and deleted |
| Whole runtime | `uv run multi-agentic-rag health-check` | PostgreSQL, Chroma, and Neo4j status |
| Ingestion success | `multi-agentic-rag ingest ...` | IDs, counts, statuses, ingestion run ID |
| Retrieval success | `multi-agentic-rag retrieve ...` | Ranked evidence chunks with source signals |
| Unit/integration behavior | `uv run pytest -q` | Default test suite passes without external services |
| Lint | `uv run ruff check .` | Style and import checks pass |
| Types | `uv run mypy src/multi_agentic_rag` | Public package type checks pass |

## Conclusion

Multi-Agentic RAG is currently a GraphRAG knowledge-base core. Its job is to store and retrieve
versioned document evidence with explicit lineage across PostgreSQL, ChromaDB, and Neo4j. Keep
new work aligned with that boundary: ingestion, persistence, graph projection, and retrieval are
in scope; user-facing chat, QA automation, API services, and generated test workflows should be
reintroduced only as separate, deliberate layers on top of this core.
