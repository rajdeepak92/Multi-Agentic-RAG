# Agentic GraphRAG QA

## Description

Agentic GraphRAG QA is a document-grounded QA automation framework for versioned engineering documents such as BRDs, SRS files, protocol specs, and test documentation. It ingests source documents, extracts traceable facts, stores metadata in PostgreSQL, indexes evidence in Weaviate, builds a Neo4j knowledge graph, plans coverage, generates pytest automation artifacts, runs them, and records results back into durable metadata and graph state.

The repository is strict by default. Current default settings target PostgreSQL, managed or remote Neo4j, Weaviate, BGE embeddings and reranking, and OpenAI-ready routing/synthesis. Local SQLite, Chroma, localhost Neo4j, and hash embeddings remain available only for tests and offline development when `ALLOW_LOCAL_DEV_MODE=true`.

Current capabilities are implemented in code. Strict-default capabilities require the configured external services to be live. Future additions are listed separately and are not implied to be complete.

## Flow Diagram

```mermaid
flowchart TD
    A[Versioned BRD / SRS / test docs] --> B[Document ingestion]
    B --> C[Chunking and fact extraction]
    C --> D[(PostgreSQL metadata registry)]
    C --> E[(Weaviate vector index)]
    C --> F[(Neo4j knowledge graph)]
    D --> G[GraphRAG retrieval]
    E --> G
    F --> G
    G --> H[LangGraph QA agents]
    H --> I[Coverage planning]
    I --> J[Generated pytest and Robot wrapper artifacts]
    J --> K[Pytest execution]
    K --> L[Coverage and result feedback]
    L --> D
    L --> F
    G --> M[Document-scoped chat]
```

The same evidence layer supports chat, delta analysis, coverage planning, testcase generation, and result feedback. In strict mode, missing graph evidence blocks GraphRAG workflows instead of silently falling back to local-only behavior.

## Clone

```powershell
git clone <repo-url>
cd Multi-Agentic-RAG
```

Use Windows PowerShell or another shell with Python 3.12 and `uv` available.

## Environment Dependencies

Required for strict target runtime:

- Python 3.12+
- `uv`
- PostgreSQL reachable from `POSTGRES_DSN`
- Neo4j reachable from `NEO4J_URI`
- Weaviate reachable from `WEAVIATE_URL`
- Hugging Face model access for `BAAI/bge-m3` and `BAAI/bge-reranker-v2-m3`
- OpenAI API access when `LLM_PROVIDER=openai`

Required Python dependencies are declared in `pyproject.toml` and locked through `uv.lock`. Managed service credentials must be supplied through `.env`; do not commit secrets.

## Setup

1. Create the virtual environment and install dependencies.

```powershell
uv sync --locked
```

2. Create `.env` from the template.

```powershell
Copy-Item .env.example .env
```

3. Fill strict runtime settings in `.env`.

```dotenv
REGISTRY_PROVIDER=postgresql
POSTGRES_DSN=postgresql+psycopg://marag_user:change-me@postgres.example.com:5432/marag
NEO4J_URI=neo4j+s://neo4j.example.com
WEAVIATE_URL=https://weaviate.example.com
EMBEDDING_PROVIDER=huggingface
RERANKER_PROVIDER=huggingface
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-change-me
ALLOW_LOCAL_DEV_MODE=false
```

4. Validate strict readiness.

```powershell
uv run multi-agentic-rag doctor --system PROJECT_1 --version v1
```

If external services are not configured, this command fails by design. For local tests and offline development only, enable the local override block in `.env`:

```dotenv
MARAG_TARGET_MODE=local
ALLOW_LOCAL_DEV_MODE=true
GRAPHRAG_REQUIRED=false
REGISTRY_PROVIDER=sqlite
VECTOR_STORE_PROVIDER=chroma
EMBEDDING_PROVIDER=hash
RERANKER_PROVIDER=none
LLM_PROVIDER=none
NEO4J_URI=bolt://127.0.0.1:7687
WEAVIATE_URL=
OPENAI_API_KEY=
```

## Additional Tools

- `uv run pytest -q` runs the repository test suite.
- `uv run multi-agentic-rag --help` shows CLI commands.
- `uv run multi-agentic-rag api` starts the FastAPI service.
- `uv run multi-agentic-rag mcp-info` prints the current MCP placeholder boundary.
- PyMuPDF, pdfplumber, and python-docx handle document parsing.
- Tesseract OCR is optional and used only when `ENABLE_PDF_OCR=true`.
- Neo4j Desktop helper scripts are local-dev conveniences, not strict target requirements.

## Use Cases

- Ingest BRD/SRS versions and ask only evidence-backed questions.
- Detect V1 to V2 fact deltas and link impact back to requirements.
- Generate requirement coverage scenarios from document evidence.
- Generate pytest automation artifacts with JSON sidecars and Robot wrapper files.
- Execute generated pytest files, record pass/fail/blocked/skipped results, and link them back to coverage.
- Reuse unchanged V1-linked coverage when V2 does not change the underlying requirement evidence.

## Benefits

- Evidence-gated answers: no evidence means no supported answer.
- Version-aware truth: active and superseded documents are kept separate.
- Graph-backed planning: strict target mode requires Neo4j evidence for GraphRAG workflows.
- Deterministic local testing: offline tests can still use SQLite, Chroma, and hash embeddings with an explicit flag.
- Traceable automation: generated tests carry document, chunk, fact, coverage, run, and result identifiers.
- Dependency-aware execution: missing real devices, simulators, or protocol endpoints are marked blocked/skipped rather than faked as passing.

## Feasibility Matrix

<table>
  <thead>
    <tr>
      <th>Capability</th>
      <th>Tool/tech</th>
      <th>Current status</th>
      <th>Strict default</th>
      <th>Why chosen this tool/tech</th>
    </tr>
  </thead>
  <tbody>
    <tr><th colspan="5">Runtime And Interfaces</th></tr>
    <tr>
      <td>CLI workflows</td>
      <td>Typer and Rich</td>
      <td>Implemented</td>
      <td>Enabled</td>
      <td>Provides typed commands and readable terminal output for operator runbooks.</td>
    </tr>
    <tr>
      <td>HTTP service</td>
      <td>FastAPI</td>
      <td>Implemented</td>
      <td>Enabled when started</td>
      <td>Exposes the same service functions behind a lightweight API boundary.</td>
    </tr>
    <tr>
      <td>Agent orchestration</td>
      <td>LangGraph with Python node services</td>
      <td>Implemented with conditional gates</td>
      <td>Enabled</td>
      <td>Keeps routing, evidence checks, generation, execution, and reporting as inspectable nodes.</td>
    </tr>
    <tr><th colspan="5">Storage And Retrieval</th></tr>
    <tr>
      <td>Metadata registry</td>
      <td>PostgreSQL through psycopg</td>
      <td>Implemented</td>
      <td>Required</td>
      <td>Provides durable relational state for documents, facts, deltas, coverage, generated files, and results.</td>
    </tr>
    <tr>
      <td>Local registry</td>
      <td>SQLite</td>
      <td>Implemented</td>
      <td>Blocked unless local-dev mode is enabled</td>
      <td>Supports deterministic offline tests without requiring managed infrastructure.</td>
    </tr>
    <tr>
      <td>Vector retrieval</td>
      <td>Weaviate</td>
      <td>Implemented</td>
      <td>Required</td>
      <td>Combines vector and BM25-style retrieval behind an external scalable vector service.</td>
    </tr>
    <tr>
      <td>Local vector fallback</td>
      <td>ChromaDB</td>
      <td>Implemented</td>
      <td>Blocked unless local-dev mode is enabled</td>
      <td>Supports repeatable developer tests and demos without a vector service.</td>
    </tr>
    <tr>
      <td>Knowledge graph</td>
      <td>Neo4j</td>
      <td>Implemented</td>
      <td>Required for GraphRAG</td>
      <td>Stores document lineage, facts, requirement links, generated tests, coverage, and run results as graph context.</td>
    </tr>
    <tr><th colspan="5">AI And Ranking</th></tr>
    <tr>
      <td>Embeddings</td>
      <td>BAAI/bge-m3 via sentence-transformers</td>
      <td>Implemented</td>
      <td>Required</td>
      <td>Provides strong multilingual/general retrieval embeddings without changing vector-store contracts.</td>
    </tr>
    <tr>
      <td>Reranking</td>
      <td>BAAI/bge-reranker-v2-m3</td>
      <td>Implemented</td>
      <td>Required</td>
      <td>Improves evidence ordering before extractive or LLM-assisted answers are produced.</td>
    </tr>
    <tr>
      <td>Structured LLM routing and synthesis</td>
      <td>OpenAI Responses API</td>
      <td>Implemented as optional runtime path</td>
      <td>Configured by default</td>
      <td>Provides structured decisions while preserving deterministic fallbacks and evidence validation.</td>
    </tr>
    <tr>
      <td>Offline embeddings</td>
      <td>Deterministic hash embeddings</td>
      <td>Implemented</td>
      <td>Blocked unless local-dev mode is enabled</td>
      <td>Keeps tests fast, deterministic, and independent of model downloads.</td>
    </tr>
    <tr><th colspan="5">Document Understanding</th></tr>
    <tr>
      <td>PDF parsing</td>
      <td>PyMuPDF and pdfplumber</td>
      <td>Implemented</td>
      <td>Enabled</td>
      <td>Handles common engineering PDF text extraction paths with fallback parser coverage.</td>
    </tr>
    <tr>
      <td>DOCX parsing</td>
      <td>python-docx</td>
      <td>Implemented</td>
      <td>Enabled</td>
      <td>Supports business and requirements documents distributed as Word files.</td>
    </tr>
    <tr>
      <td>Fact extraction</td>
      <td>Rule extractors plus optional LLM fallback</td>
      <td>Implemented</td>
      <td>Rule extraction always available; LLM requires provider readiness</td>
      <td>Preserves deterministic facts first and uses LLM extraction only when evidence remains source-grounded.</td>
    </tr>
    <tr><th colspan="5">QA Automation</th></tr>
    <tr>
      <td>Coverage planning</td>
      <td>Graph-backed scenario selection with registry fallback only in local mode</td>
      <td>Implemented</td>
      <td>Graph evidence required</td>
      <td>Ensures scenarios are tied to requirement evidence and graph lineage in target runs.</td>
    </tr>
    <tr>
      <td>Generated tests</td>
      <td>pytest files, JSON sidecars, harness files</td>
      <td>Implemented</td>
      <td>Enabled</td>
      <td>Creates executable Python artifacts that preserve traceability and dependency status.</td>
    </tr>
    <tr>
      <td>Robot wrapper</td>
      <td>Generated Robot Framework file</td>
      <td>Generated wrapper only</td>
      <td>Generated when test artifacts are written</td>
      <td>Provides a future integration surface while pytest remains the current execution engine.</td>
    </tr>
    <tr>
      <td>Execution tracking</td>
      <td>pytest, JUnit XML, registry rows, graph links</td>
      <td>Implemented</td>
      <td>Enabled</td>
      <td>Captures pass/fail/skipped/blocked results and links them to generated tests and coverage.</td>
    </tr>
    <tr><th colspan="5">Operations And Safety</th></tr>
    <tr>
      <td>Readiness checks</td>
      <td><code>multi-agentic-rag doctor</code></td>
      <td>Implemented</td>
      <td>Strict automatically in target mode</td>
      <td>Surfaces missing providers and graph readiness before ingestion or generation.</td>
    </tr>
    <tr>
      <td>Local cleanup</td>
      <td><code>clean-system-state</code></td>
      <td>Implemented for SQLite/Chroma/local files</td>
      <td>Blocked in PostgreSQL target mode</td>
      <td>Prevents accidental managed-state deletion while preserving a local reset path.</td>
    </tr>
    <tr>
      <td>Object artifacts</td>
      <td>Local filesystem</td>
      <td>Implemented</td>
      <td>Enabled for this pass</td>
      <td>Stores parsed chunks and copied source artifacts simply while managed object storage remains future work.</td>
    </tr>
  </tbody>
</table>

## Future Additions

- Managed object storage for parsed artifacts and generated reports.
- Real Robot Framework execution, not only generated wrapper files.
- Domain plugin packs for richer extractors, simulators, protocol adapters, and validation keywords.
- Human review UI for coverage scenarios, evidence, and generated testcase approval.
- CI/CD integration for strict service readiness and scheduled regression execution.
- Richer graph analytics for impact propagation and requirement risk scoring.

## Execution Flows

### 1. Ingest facts and answer from evidence

```powershell
uv run multi-agentic-rag doctor --system PROJECT_1 --version v1
uv run multi-agentic-rag ingest documents/inbox/PROJECT_1/SIIMCS_BRD_V1.pdf --system PROJECT_1 --version v1
uv run multi-agentic-rag query "What is the current temperature threshold?" --system PROJECT_1 --version v1
```

`query` requires `--system`. Framework, setup, and out-of-scope questions are rejected by document-scoped chat.

### 2. Generate and execute tests

```powershell
uv run multi-agentic-rag coverage-plan --system PROJECT_1 --version v1 --count 25
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 25
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 25
uv run multi-agentic-rag last-results --system PROJECT_1 --version v1
```

Generated tests are dependency-aware. Missing devices, simulators, brokers, or endpoints are reported as blocked/skipped, not as fake passes.

### 3. V1 to V2 update and delta

```powershell
uv run multi-agentic-rag ingest documents/inbox/PROJECT_1/SIIMCS_BRD_V1.pdf --system PROJECT_1 --version v1
uv run multi-agentic-rag ingest documents/inbox/PROJECT_1/SIIMCS_BRD_V2.pdf --system PROJECT_1 --version v2
uv run multi-agentic-rag delta --system PROJECT_1 --from v1 --to v2
```

The registry keeps superseded V1 evidence and active V2 evidence separately. Delta claims are made only when stored fact deltas exist.

### 4. Post-update coverage reuse and selective execution

```powershell
uv run multi-agentic-rag coverage-plan --system PROJECT_1 --version v2 --count 25
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v2 --count 25
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v2 --count 25
```

Unchanged V1-linked scenarios are reused and skipped by default. To execute reused scenarios too:

```powershell
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v2 --count 25 --force-run-all
```

### 5. Document-scoped chat

```powershell
uv run multi-agentic-rag query "What are the covered areas of BRD V2?" --system PROJECT_1 --version v2
```

The chat path answers only from selected project evidence. It rejects missing `--system`, framework questions, setup questions, and questions where no evidence exists.

## Domain Adaptability

The framework is domain-adaptable because document parsing, fact extraction, graph indexing, coverage planning, and generated execution adapters are separate layers. The current extraction rules handle requirements, thresholds, protocols, sensors, endpoints, topics, and test references. The generated-test layer records protocol dependency status for REST, MQTT, Modbus, and CAN-style evidence.

New domains should add extractors and validation adapters without changing the registry contract. The durable identifiers are document, chunk, fact, semantic key, coverage, generated file, and test-result IDs.

## Domain Challenges

- Ambiguous requirements need human review before automation can be trusted.
- Scanned PDFs may require OCR and still need manual quality checks.
- Domain tables can be parsed differently across PDFs, DOCX files, and exporter versions.
- Real hardware and simulators are often unavailable during generation, so execution may be blocked by design.
- Protocol evidence may be enough to generate placeholders but not enough to create a real integration test.
- Version labels in filenames and CLI arguments must match; mismatches are rejected.

## Fallbacks

- No evidence -> no supported answer.
- No delta rows -> no impact claim.
- Missing Neo4j graph evidence in strict GraphRAG mode -> workflow blocks.
- Missing PostgreSQL DSN in strict mode -> registry initialization fails.
- Missing Weaviate URL in strict mode -> vector provider readiness fails.
- Hash embeddings, SQLite, Chroma, and localhost Neo4j -> allowed only when `ALLOW_LOCAL_DEV_MODE=true`.
- Missing real protocol/device dependencies -> generated pytest execution blocks or skips.
- Explicit `--mock` -> no real connection is established, and generated artifacts label the run as mock mode.

## Conclusion

Agentic GraphRAG QA is built to keep QA automation evidence-bound, version-aware, and operationally honest. Strict defaults target managed GraphRAG infrastructure. Local fallbacks remain available for deterministic development, but only behind an explicit switch so production-like runs fail loudly when required services or evidence are missing.
