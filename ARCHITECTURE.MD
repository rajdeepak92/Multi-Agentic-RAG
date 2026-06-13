# multi-agentic-rag Architecture

## Current Phase

The current implementation is a local-first Multi-Agentic RAG foundation with a
document-grounded, dependency-aware pytest automation generator.

```text
Knowledge graph + vector retrieval + BM25 keyword retrieval
+ evidence-linked coverage planning
+ generated pytest automation artifacts
+ JSON and SQLite testcase run tracking
```

The system is aimed at QA engineers and analysts working with versioned BRD,
SRS, design, and protocol documents. The current generated automation blocks
missing protocol/device dependencies instead of faking external calls, and
every generated test must still trace to document evidence.

## Strategic Roadmap

`STRATEGIC_UPDATE_PLAN.md`, `UPDATED_GOAL.md`, `EXECUTION_FLOW.md`,
`TEST_GENERATION_STRATEGY.md`, `ARCHITECTURE_TARGET.mermaid`, and
`feasibility.md` record the planned shift toward LangGraph-orchestrated QA
automation, graph-backed planning, domain adapters, and mock/simulator-backed
pytest generation. This architecture document remains the current-state
technical description.

## Scientific Contract

- No evidence -> no answer.
- No version -> no truth.
- No delta -> no impact claim.
- No requirement link -> no coverage claim.

Old evidence is preserved. Superseded documents are marked by status and
lineage, not hard-deleted.

## Main Workflows

One intent router fronts three practical workflows:

1. `ingest_document`: parse documents, extract facts, update stores.
2. `generate_test_automation`: plan coverage, write dependency-aware pytest artifacts,
   execute them when requested, and track results.
3. `answer_document_question`: retrieve evidence and answer conservatively.

The task router uses service-backed LangGraph workflow wrappers. The generation
internals are still deterministic Python services and can be split into finer
LangGraph nodes over time.

## Runtime Boundaries

| Boundary | Current implementation | Production direction |
| --- | --- | --- |
| CLI | Typer commands through `multi-agentic-rag` and `multi-rag` | Keep as local/operator interface |
| API | FastAPI routes for health, doctor, documents, query, delta, coverage, tasks, tests | Add auth and production deployment |
| Metadata | SQLite registry | PostgreSQL |
| Keyword | SQLite FTS5 BM25 | OpenSearch BM25 |
| Vector | Weaviate adapter when configured | Weaviate self-hosted/cloud |
| Vector fallback | ChromaDB persistent local store | Development fallback only |
| Graph | Neo4j Python driver with Cypher templates | Neo4j managed or on-prem cluster |
| Object store | Local filesystem objects | MinIO/S3 |
| Parsing | PyMuPDF, pdfplumber, python-docx, optional OCR | Same pipeline with workers/queue later |
| Test harness | Generated pytest files, `pytest.ini`, `conftest.py`, fixtures, markers, logging | Real interface clients after dependency audit |
| LLM | Configured but not required for deterministic local flows | OpenAI for routing, planning, debugging, generation |
| Embeddings | BAAI/bge-m3 through HuggingFace; hash fallback for tests | Open-source-first embeddings, managed fallback only if approved |
| MCP | Placeholder command only | Full MCP server reusing the same services |

Docker is intentionally not required for the local workflow.

## Ingestion Flow

1. CLI or FastAPI receives a file/folder, system name, and version.
2. The source file is hashed and copied into `.multi_agentic_rag/documents`.
3. PDFs are parsed with PyMuPDF.
4. Tables are appended through pdfplumber when available.
5. DOCX files are parsed through python-docx.
6. Optional OCR runs only when enabled and needed for scanned content.
7. Chunks preserve source, page, section, system, version, and hash metadata.
8. Deterministic extractors create facts for:
   - requirements
   - devices
   - sensors
   - thresholds and units
   - Modbus registers/coils
   - CAN IDs
   - REST endpoints
   - MQTT topics
   - test case IDs
9. SQLite stores documents, chunks, facts, deltas, coverage, generated files,
   and test run results.
10. SQLite FTS5 indexes chunks for BM25 keyword retrieval.
11. Parsed chunks are written as JSONL under `.multi_agentic_rag/objects`.
12. Vectors are indexed in Weaviate when configured, otherwise ChromaDB.
13. Neo4j graph nodes and edges are upserted when Neo4j is reachable.

## Version Lifecycle

When a newer version is ingested:

```text
newer active document -[:SUPERSEDES]-> older document
```

Behavior:

- Previous active documents become `superseded`.
- Previous chunks and facts become `superseded`.
- Current documents become `active`.
- Deterministic deltas are stored.
- Keyword and vector indexes are updated with current statuses.
- Same-version replacements are archived instead of treated as new current
  truth.

Version-scoped queries can still inspect older evidence explicitly.

## Graph Ontology

Primary labels:

- `System`
- `Document`
- `Chunk`
- `Requirement`
- `Fact`
- `Entity`
- `Sensor`
- `Device`
- `Protocol`
- `Topic`
- `TestCase`
- `GeneratedTest`
- `TestRun`
- `Delta`
- `Coverage`

Primary relationships:

- `HAS_DOCUMENT`
- `HAS_CHUNK`
- `SUPPORTS_FACT`
- `DESCRIBES_REQUIREMENT`
- `TRACES_TO_REQUIREMENT`
- `MENTIONS`
- `THRESHOLD_FOR`
- `IMPLEMENTS_PROTOCOL`
- `DETAILS_PROTOCOL`
- `USES_TOPIC`
- `VERIFIED_BY`
- `SUPERSEDES`
- `FROM_DOCUMENT`
- `TO_DOCUMENT`
- `COVERS_REQUIREMENT`
- `HAS_GENERATED_TEST`
- `IMPLEMENTS_COVERAGE`
- `HAS_TEST_RUN`
- `SUPPORTED_BY_CHUNK`

Extraction metadata uses governance hints such as `sosa:Sensor`,
`sosa:ObservableProperty`, and `ssn:System` only where deterministic rules can
assign them safely.

## Retrieval Flow

Hybrid retrieval combines:

1. Graph retrieval through bounded Neo4j Cypher templates.
2. Vector retrieval through Weaviate or ChromaDB.
3. Keyword retrieval through SQLite FTS5/BM25.
4. Registry lookup for deterministic facts, deltas, coverage, and generated
   testcase records.

Results are deduped by chunk and fact ID before rendering. The current answer
path is conservative and deterministic; an LLM answer layer must cite retrieved
evidence instead of inventing claims.

## Test Automation Generation Flow

The implemented handoff for test automation is:

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

Current status:

- The task router runs through service-backed LangGraph workflow wrappers.
- The handoff is recorded in generated JSON.
- Services are implemented as deterministic Python functions and can be split
  into finer graph nodes over time.
- OpenAI is the intended reasoning model for routing, scenario reasoning, test
  planning, and debugging.
- HuggingFace embeddings/rerankers are optional model-backed retrieval
  components.
- BM25 remains the exact keyword retrieval layer for IDs, endpoints, protocols,
  and requirement language.

## Coverage Planning

Coverage planning requires stored requirement evidence for the requested
`system/version`.

Each coverage record stores:

- `coverage_id`
- `requirement_id`
- `document_id`
- `version`
- `chunk_id`
- `source_hash`
- evidence text
- scenario index
- priority
- draft coverage status

The planner creates a document-scope hash from ingested document IDs, versions,
and content hashes. If a completed plan already exists for the same scope and
scenario count, MARAG reuses it instead of regenerating.

## Generated Artifact Layout

For:

```powershell
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 10
```

Artifacts are written to:

```text
generated/
  project_1/
    brd_v1/
      test_project_1_brd_v1.py
      test_project_1_brd_v1.json
      conftest.py
      pytest.ini
```

`generated/` is ignored by git and excluded from normal project pytest
discovery. MARAG executes generated tests explicitly from the artifact folder.

## Generated Pytest Behavior

Generated tests are class-based pytest scripts.

The generated harness includes:

- `pytest.ini` with addopts, log CLI configuration, and markers.
- `conftest.py` with `pytest_addoption`, `pytest_configure`, session fixture,
  and autouse logging fixture.
- `generated`, `evidence_bound`, and `requirement(id)` markers.
- Class methods that assert traceability fields before calling dependency-aware
  validation.

Each generated test checks:

- `coverage_id` is part of the generated coverage set.
- `requirement_id` is present.
- Evidence exists.
- At least one chunk ID exists.
- Expected values came from evidence.
- Missing external dependencies are skipped/blocked.
- Mock-mode or document-contract validation returns `True`.

The validation helper logs:

- `DEBUG` for scenario data.
- `ERROR` for dependency blockers.
- `INFO` for validation mode and label.

It does not call real MQTT, REST, CAN, Modbus, device, or application
interfaces unless the dependency audit has configuration for that target.

## Tracking JSON Contract

Each generated test file has a sidecar JSON file.

Top-level fields include:

- `schema_version`
- `system_name`
- `doc_version`
- `generated_test_file`
- `coverage_run_id`
- `scope_hash`
- `generated_file`
- `tracking_file`
- `harness_files`
- `mode`
- `workflow_handoff`
- `retry_policy`
- `dependency_audit`
- `selected_scenarios`
- `requirements`
- `evidence_refs`
- `protocols`
- `domain`
- `scenarios`
- `run_history`

Each scenario stores:

- `requirement_id`
- `source_doc`
- `source_doc_id`
- `doc_version`
- `chunk_ids`
- `expected_values`
- `priority`
- `test_scenario`
- `generated_file`
- `test_function`
- `evidence`
- `last_run_status` after execution

After execution, the runner appends `run_1`, `run_2`, and so on, plus a
normalized `run_history` item with `PASS`, `FAIL`, `SKIP`, or `BLOCKED`.

SQLite also stores generated test file records and test result records. When
Neo4j is configured, generated tests, coverage records, and run results are
mirrored as graph traceability nodes. The JSON is currently the detailed trace
artifact and can later become an export of a database trace table.

## Execution And Retry

`run-testcases` performs:

```text
generate or reuse artifacts
-> validate Python syntax with py_compile
-> run pytest from the generated artifact folder
-> parse passed, failed, skipped counts
-> classify dependency/service blockers
-> store result in SQLite
-> update sidecar JSON run history
```

Retry behavior:

- Maximum 5 attempts.
- Regenerate only for fixable generated-code failures.
- Missing modules, import errors, connection refused, timeouts, and unavailable
  protocol services are environment blockers.
- Blockers are recorded instead of causing blind code rewrites.

## Dependency Audit Boundary

The generator does not freely mutate project dependencies.

Generated tests always require:

- Python
- pytest
- logging
- generated `pytest.ini`
- generated `conftest.py`

Future real-interface tests must route missing MQTT/REST/CAN/Modbus clients or
service configuration through `DependencyAuditAgent` first. That agent should
propose project-level changes and apply them only through an approved
implementation step.

## API And CLI Surface

Current CLI commands include:

- `init`
- `doctor`
- `graph-check`
- `demo-pdf`
- `demo-run`
- `validate-real-brd`
- `ingest-real-brd`
- `ingest-doc`
- `ingest-folder`
- `query`
- `delta`
- `coverage`
- `coverage-plan`
- `generate-tests`
- `run-testcases`
- `last-results`
- `task`
- `api`
- `mcp-info`

Current API endpoints:

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

## Not Built Yet

- Full MCP server.
- PostgreSQL backend.
- OpenSearch backend.
- MinIO/S3 backend.
- Production auth and UI.
- Advanced semantic delta.
- Real protocol/device/application interface tests.
- LLM extraction and final answer generation beyond deterministic evidence.
- Fully compiled LangGraph multi-agent execution graph.
- Production deployment automation.

See `ARCHITECTURE.mermaid` for the visual flow and `execution.md` for the
operator-level execution guide.
