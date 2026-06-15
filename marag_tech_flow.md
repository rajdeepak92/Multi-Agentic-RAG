# MARAG Technical Flow And Current Gap Review

## Purpose

This document explains what actually happens when the current MARAG commands run,
which technologies are used, which target Option-4 capabilities are active, and
which gaps still block the intended Knowledge Graph + GraphRAG + Multi-Agent QA
automation architecture.

This is a current-state review. It does not claim that the target architecture
is complete.

## Short Verdict

The current flow is working as a local-first deterministic MARAG prototype, but
it is not yet working as the full intended Option-4 architecture.

What is active now:

- Typer CLI through `uv run multi-agentic-rag ...`.
- SQLite registry for documents, chunks, facts, deltas, coverage, generated
  tests, and execution results.
- SQLite FTS5/BM25 keyword retrieval.
- Chroma vector store.
- Hash embeddings in this live checkout.
- PyMuPDF and pdfplumber parsing.
- LangChain text splitting.
- Deterministic rule-based fact extraction.
- Neo4j graph writes and basic graph fact retrieval when the query path allows
  it.
- Service-backed LangGraph workflow wrapper for natural-language `task`.
- Deterministic coverage planning.
- Generated class-based pytest artifacts plus JSON sidecar.
- `py_compile` and pytest execution.
- PASS/FAIL/SKIP/BLOCKED result classification.

What is now active behind configuration:

- Local-first default mode remains deterministic: hash embeddings, SQLite,
  Chroma, BM25, deterministic extraction, pytest generation, and optional Neo4j.
- `--target-graphrag` doctor mode validates the stricter Option-4 stack:
  Neo4j, `BAAI/bge-m3`, `BAAI/bge-reranker-v2-m3`, OpenAI, graph population,
  and REST/MQTT simulator readiness.
- OpenAI/Azure clients can perform structured intent routing, conservative
  fallback extraction, and evidence-bounded answer synthesis when enabled.
- Graph-backed scenario selection is enforced when `MARAG_TARGET_MODE` is
  `target-graphrag` or `GRAPHRAG_REQUIRED=true`.
- Reranking is active when `RERANKER_PROVIDER=huggingface`.
- REST/MQTT simulator readiness is modeled; generated pytest calls simulator
  validation in simulator mode.
- Safe REST GET real-adapter validation exists for explicit real REST mode;
  unsupported real protocols produce `PROTOCOL_UNAVAILABLE` instead of fake
  passes.
- Robot Framework mapping files are generated only when
  `ROBOT_GENERATION_ENABLED=true`.

Still intentionally not mandatory:

- Hugging Face model downloads.
- OpenAI/Azure calls.
- Neo4j.
- Weaviate, OpenSearch, PostgreSQL, MinIO/S3.
- Robot execution.
- Docker/Kubernetes.
- Real Modbus/MQTT/CAN adapters.

Neo4j extraction remains a non-goal: extraction happens before graph storage
through deterministic Python extractors plus optional evidence-gated LLM
fallback; Neo4j stores and retrieves graph knowledge.

## Implementation Update: Local Mode Vs Target GraphRAG Mode

Default local mode is designed for developer usability:

```powershell
uv run multi-agentic-rag doctor
uv run multi-agentic-rag ingest-doc <path> --system PROJECT_1 --version v1
uv run multi-agentic-rag query "..." --system PROJECT_1 --version v1
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 10
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 10
```

Target GraphRAG mode is a strict demo/validation path:

```powershell
uv run multi-agentic-rag doctor --target-graphrag --system PROJECT_1 --version v1
```

Target mode expects these settings:

```env
MARAG_TARGET_MODE=target-graphrag
GRAPHRAG_REQUIRED=true
EMBEDDING_PROVIDER=huggingface
DEFAULT_EMBEDDING_MODEL=BAAI/bge-m3
RERANKER_PROVIDER=huggingface
DEFAULT_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
LLM_PROVIDER=openai
REST_SIMULATOR_ENABLED=true
MQTT_SIMULATOR_ENABLED=true
```

If target mode is enabled, query and coverage planning must have graph evidence.
They do not silently fall back to vector/BM25-only behavior.

## Live Validation Snapshot

Read-only validation was run from `D:\Multi-Agentic-RAG`.

`uv run multi-agentic-rag doctor` showed:

- `.env`: loaded.
- Embedding provider: WARN, hash embeddings selected.
- Vector provider: Chroma using `hash:multi_agentic_rag_hash_embedding`.
- Neo4j: PASS, connection verified.
- SQLite registry, SQLite FTS5, object store, ChromaDB, and parsers: PASS.
- OpenAI key: not required because LLM provider is disabled.

Additional read-only inspection showed:

```text
embedding_provider=hash
default_embedding_model=BAAI/bge-m3
vector_store_provider=chroma
llm_provider=none
graphrag_required=False
keyword_index_enabled=True
selected_vector_store=chroma
selected_vector_reason=Using local Chroma fallback; embeddings=hash:multi_agentic_rag_hash_embedding.
project_1_documents=4
project_1_chunks=61
project_1_facts=370
project_1_v1_requirement_facts=150
latest_result_status=blocked
latest_result_counts=20,0,5
neo4j_available=True
neo4j_current_fact_records=104
neo4j_historical_fact_records=370
```

Important state warning:

`PROJECT_1` currently has stale or contaminated registry state. One older row
records `SIIMCS_BRD_V2.pdf` as `version=v1`. That can affect v1 coverage and
generated tests until the system state is cleaned or scoped more strictly.

## Command Flow From The Log

### 1. `ingest-doc`

Command:

```powershell
uv run multi-agentic-rag ingest-doc "documents\inbox\PROJECT_1\SIIMCS_BRD_V1.pdf" --system PROJECT_1 --version v1
```

Primary code path:

```text
src/multi_agentic_rag/cli.py
-> ingest_doc()
-> ingest()
-> src/multi_agentic_rag/ingestion/loader.py ingest_document()
```

What executes:

1. `uv` runs the installed console script from the local environment.
2. Typer dispatches to the `ingest-doc` command.
3. Pydantic settings load `.env`.
4. Runtime folders are created under `.multi_agentic_rag`.
5. SQLite registry is initialized.
6. The source file exists and its filename version hint is checked.
7. The source PDF is copied into the managed local document store.
8. PyMuPDF extracts page text.
9. pdfplumber attempts table extraction.
10. LangChain `RecursiveCharacterTextSplitter` chunks the extracted text.
11. Rule extractors create deterministic facts:
    - requirements
    - thresholds
    - protocols
    - protocol details
    - sensors
    - devices
    - MQTT topics
    - test IDs
12. SQLite stores documents, chunks, facts, deltas, and FTS rows.
13. Chroma indexes chunks.
14. Neo4j is checked and, if available, stores documents, chunks, facts,
    entities, and deltas.
15. Parsed chunk artifacts are written under `.multi_agentic_rag\objects`.

Why the log says `Status: superseded`:

- The registry already had a newer active `PROJECT_1` document version.
- Ingesting V1 after V2 makes this V1 historical/superseded instead of active.

Technology actually used:

| Layer | Current behavior |
| --- | --- |
| CLI | Typer |
| Environment | `.env` through Pydantic settings |
| PDF parsing | PyMuPDF, pdfplumber |
| Chunking | LangChain text splitter |
| Extraction | deterministic Python regex/table extractors |
| Registry | SQLite |
| Keyword search | SQLite FTS5/BM25 |
| Vector store | Chroma |
| Embeddings | hash in this checkout |
| Graph | Neo4j write path is active when reachable |
| LLM/OpenAI | not used |

### 2. `query`

Command:

```powershell
uv run multi-agentic-rag query "What are the covered areas of BRD V1?" --system PROJECT_1 --version v1
```

Primary code path:

```text
src/multi_agentic_rag/cli.py
-> query()
-> src/multi_agentic_rag/retrieval/hybrid_retriever.py answer_query()
```

What executes:

1. Intent is detected with deterministic rules.
2. The query is expanded for scope-related words.
3. SQLite facts are loaded for `system=PROJECT_1`, `version=v1`.
4. Chroma vector retrieval runs with the configured embedding function.
5. SQLite FTS5/BM25 keyword retrieval runs.
6. Neo4j graph fact retrieval is attempted only for active or historical status
   scoped queries.
7. Evidence chunks are deduped.
8. If exact facts match, a deterministic fact answer is rendered.
9. If no exact fact matches, chunk excerpts are rendered.

Why this answer looks weak:

- The query asks for "covered areas", but the current fact model does not store
  `scope_area` or `covered_area` facts.
- The answer falls back to chunk text extraction.
- The fallback parser treats some section labels and table fragments as scope
  bullets.
- The command passed `--version v1`, which makes status scope `None`; the
  current graph retriever does not run for explicit version scope.
- No OpenAI model is used to interpret the question or synthesize a better
  answer from evidence.

Technology actually used:

| Layer | Current behavior |
| --- | --- |
| Intent | deterministic keyword/rule detection |
| Registry facts | SQLite |
| Vector retrieval | Chroma |
| Embedding model | hash in this checkout |
| Keyword retrieval | SQLite FTS5/BM25 |
| Graph retrieval | skipped for explicit `--version v1` path |
| Answering | deterministic fact or chunk rendering |
| LLM/OpenAI | not used |

### 3. `coverage-plan`

Command:

```powershell
uv run multi-agentic-rag coverage-plan --system PROJECT_1 --version v1 --count 25
```

Primary code path:

```text
src/multi_agentic_rag/cli.py
-> coverage_plan()
-> src/multi_agentic_rag/coverage/planner.py plan_requirement_coverage()
```

What executes:

1. SQLite resolves document scope for `PROJECT_1` and `v1`.
2. SQLite loads requirement facts.
3. A scope hash is built from the scoped document IDs, versions, and hashes.
4. Existing completed coverage runs are reused unless `--force` is passed.
5. New records are generated by cycling requirement facts through fixed scenario
   templates.
6. Coverage records and coverage run metadata are stored in SQLite.

Technology actually used:

| Layer | Current behavior |
| --- | --- |
| Scenario source | SQLite requirement facts |
| Scenario selection | deterministic template cycling |
| Graph planning | not used |
| Vector retrieval | not used |
| LLM/OpenAI | not used |

Current risk:

- Because `PROJECT_1` has dirty v1 rows, the v1 coverage scope can include
  evidence from documents that should not belong to V1.

### 4. `generate-tests`

Command:

```powershell
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 10
```

Primary code path:

```text
src/multi_agentic_rag/cli.py
-> generate_tests()
-> src/multi_agentic_rag/testing/generator.py generate_testcases()
```

What executes:

1. Coverage is generated or reused.
2. Artifact folder is resolved:

```text
generated\project_1\brd_v1
```

3. The generator creates or reuses:

```text
test_project_1_brd_v1.py
test_project_1_brd_v1.json
conftest.py
pytest.ini
```

4. Scenario payloads are built from coverage evidence.
5. Expected values are extracted deterministically from evidence text.
6. Protocol mentions are detected from evidence.
7. Dependency audit marks protocol scenarios as blocked when required endpoints,
   brokers, devices, or simulator config are missing.
8. SQLite stores generated test file metadata.
9. Neo4j mirrors generated-test and coverage lineage when available.

Technology actually used:

| Layer | Current behavior |
| --- | --- |
| Test framework | pytest |
| Harness | generated `pytest.ini` and `conftest.py` |
| Sidecar | JSON schema `test-automation-tracking.v2` |
| Dependency audit | deterministic protocol/config checks |
| Graph traceability | Neo4j best effort |
| Protocol calls | not implemented |
| LLM/OpenAI | not used |

Current limitation:

- Generated tests are dependency-aware placeholders. They prove traceability,
  evidence binding, syntax validity, and dependency classification. They do not
  yet validate live protocol behavior.

### 5. `run-testcases`

Commands:

```powershell
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 10
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 5
```

Primary code path:

```text
src/multi_agentic_rag/cli.py
-> run_testcases_command()
-> src/multi_agentic_rag/testing/runner.py run_testcases()
```

What executes:

1. Generated tests are generated or reused.
2. `py_compile` checks generated Python syntax.
3. pytest runs from inside the generated artifact folder:

```text
python -m pytest test_project_1_brd_v1.py
```

4. stdout/stderr are captured.
5. pass/fail/skip counts are parsed from pytest output.
6. blocker text is detected.
7. final status is classified:
   - blockers -> `blocked`
   - failed assertions -> `failed`
   - skipped without passes -> `skipped`
   - return code 0 without blockers -> `passed`
8. SQLite stores the test run result.
9. JSON sidecar `run_history` is updated.
10. Neo4j mirrors test-run lineage when available.

Why `5 passed` can happen:

- Scenarios without protocol dependencies execute as document-contract tests.
- These validate generated artifact structure and evidence links.

Why later `20 passed, 0 failed, 5 skipped` becomes `blocked`:

- Some scenarios mention REST/MQTT protocol behavior.
- No REST API base URL, MQTT broker URL, or simulator config is configured.
- The generated tests skip those scenarios with blocker messages.
- The runner classifies blocker messages as `blocked`.

This matches `feasibility.md`: generated tests must not fake protocol or device
calls, and missing dependencies must be SKIP or BLOCKED.

### 6. `last-results`

Command:

```powershell
uv run multi-agentic-rag last-results --system PROJECT_1 --version v1
```

Primary code path:

```text
src/multi_agentic_rag/cli.py
-> last_results()
-> src/multi_agentic_rag/testing/runner.py get_last_test_result()
```

What executes:

1. SQLite reads the latest stored result for `PROJECT_1` and `v1`.
2. No pytest run happens.
3. CLI prints the result table.

This path worked in the provided log.

### 7. Natural-language `task`

Commands:

```powershell
uv run multi-agentic-rag task "Generate 15 testcases for BRD V1" --system PROJECT_1 --version v1
uv run multi-agentic-rag task "Run the testcases for BRD V1" --system PROJECT_1 --version v1
uv run multi-agentic-rag task "Show me the last test result for BRD V1" --system PROJECT_1 --version v1
```

Primary code path:

```text
src/multi_agentic_rag/cli.py
-> task()
-> src/multi_agentic_rag/tasks.py handle_task()
-> src/multi_agentic_rag/agents/workflows.py run_task_workflow()
-> src/multi_agentic_rag/agents/graph.py compile_graph()
-> src/multi_agentic_rag/agents/nodes.py
```

What executes:

1. A LangGraph workflow is compiled when LangGraph is importable.
2. The graph runs coarse service-backed nodes:
   - `route_input`
   - `ingest_document`
   - `build_graph`
   - `compute_delta`
   - `route_query`
   - `retrieve_context`
   - `verify_evidence`
   - `generate_output`
3. The route is selected by keyword rules, not an LLM.
4. Terminal actions call the same services used by direct CLI commands.

Observed task issues:

- `"Generate 15 testcases for BRD V1"` did not use the number `15`; the CLI
  default `--count 25` was used because natural-language count extraction is not
  implemented.
- `"Show me the last test result for BRD V1"` was misrouted to query because the
  router matches `"last result"`, `"previous result"`, or `"show result"`, but
  not `"last test result"`.

Technology actually used:

| Layer | Current behavior |
| --- | --- |
| Orchestration | LangGraph wrapper if installed, fallback sequential runner otherwise |
| Intent routing | deterministic keyword rules |
| Parameter extraction | CLI options only; no natural-language count parsing |
| Tool execution | Python service calls |
| OpenAI reasoning | not used |

## Current Flow Compared To `feasibility.md`

| Area | Feasibility intent | Current validation | Verdict |
| --- | --- | --- | --- |
| Local-first execution | Local-first current mode | Active | aligned |
| Open-source-first | Default architecture | Active | aligned |
| Paid APIs optional | Optional/configurable | LLM disabled | aligned, but no optional LLM path yet |
| Neo4j knowledge graph | Current optional/local, target required | Neo4j available and populated, but `GRAPHRAG_REQUIRED=false` | partially aligned |
| GraphRAG as reasoning layer | Target primary | Graph is basic retrieval/traceability, not planning backbone | gap |
| Embeddings | BAAI/bge-m3 current config | Live `.env` uses hash | gap in local runtime |
| Keyword search | SQLite FTS5/BM25 | Active | aligned |
| Metadata registry | SQLite | Active | aligned |
| Deterministic extraction | Current | Active | aligned |
| LLM extraction fallback | Future | Not active | expected gap |
| Answering | Deterministic current, optional LLM future | Deterministic only | aligned with current, not target LLM |
| LangGraph workflow | Current wrapper, target deeper graph | Coarse service-backed graph | aligned with current, gap vs target |
| Coverage planning | Scenario selector target | Deterministic template cycling | gap |
| Dependency audit | Current | Active | aligned |
| Generated pytest | Current scaffold | Active | aligned |
| Real protocols | Future | Not implemented, blocked honestly | expected gap |
| Missing dependencies | SKIP/BLOCKED | Active | aligned |
| Reports | Future | CLI/table/sidecar only | gap |

## Root Causes Behind The Log Symptoms

### Embeddings look local because they are local hash embeddings

The code supports Hugging Face embeddings through `sentence-transformers`, but
the live settings select hash embeddings. Chroma is still used, but semantic
retrieval quality is not BGE quality.

Root cause:

```text
EMBEDDING_PROVIDER=hash
VECTOR_STORE_PROVIDER=chroma
```

Needed change:

```text
EMBEDDING_PROVIDER=huggingface
DEFAULT_EMBEDDING_MODEL=BAAI/bge-m3
```

Then re-ingest the documents so Chroma stores real BGE vectors.

### Neo4j is used, but not as the planning backbone

Neo4j writes are active and graph fact records exist. However:

- explicit `--version v1` query path does not call graph retrieval because
  graph retrieval currently needs active or superseded status scope.
- coverage planning reads SQLite requirement facts, not graph paths.
- scenario selection does not use requirement-to-protocol-to-threshold
  relationships.
- generated test/run graph indexing is traceability, not decision-making.

### OpenAI is not used

The current code has `llm_provider` settings and an LLM extractor placeholder,
but no OpenAI client is wired into:

- intent routing
- count/version parsing
- fact extraction
- scenario planning
- answer synthesis
- failure debugging

This is consistent with `LLM_PROVIDER=none` and the current deterministic
phase, but it is not the intended "OpenAI main brain" behavior.

### Natural-language task routing is too shallow

The task router is keyword based. It does not parse:

- "15" from "Generate 15 testcases".
- "last test result" as a last-result request.
- richer task slots such as version aliases, output format, or target execution
  mode.

### Test execution is honest but still blocked for protocol behavior

Generated tests do not fake REST, MQTT, Modbus, or CAN calls. When config is
missing, protocol scenarios skip and the runner reports `blocked`.

That is correct according to feasibility, but the next implementation stage must
add simulators/adapters so blocked scenarios can become executable tests.

### Current `PROJECT_1` registry state is contaminated

The live registry contains:

```text
SIIMCS_BRD_V2.pdf | version=v1 | status=superseded
SIIMCS_BRD_V1.pdf | version=v1 | status=superseded
SIIMCS_BRD_V2.pdf | version=v2 | status=active
SIIMCS_BRD_V1.pdf | version=v1 | status=superseded
```

This explains why generated V1 artifacts can reference V2 evidence. Before
using `PROJECT_1` as a proof run, state should be cleaned and documents should
be re-ingested in the intended order.

## Implementation Plan To Overcome The Blockers

### Phase 0: Make Current Runtime Truth Visible

Goal:

Make every command show which providers and stores it actually used.

Implement:

1. Extend `IngestResult` and CLI output with:
   - embedding provider
   - embedding model
   - vector provider
   - graph write status
   - keyword index status
2. Extend `QueryResult` CLI output with retrieval sources:
   - registry
   - graph
   - vector
   - keyword
3. Add a `doctor --target-graphrag` mode that fails when:
   - `EMBEDDING_PROVIDER=hash`
   - Neo4j is unavailable
   - `GRAPHRAG_REQUIRED=false`
   - `LLM_PROVIDER` is requested but credentials are missing
4. Add a scoped `reset-system` or `clean-system-state` command for local
   cleanup across:
   - SQLite rows
   - Chroma chunks
   - Neo4j nodes
   - `.multi_agentic_rag` managed artifacts

Validation:

```powershell
uv run multi-agentic-rag doctor --target-graphrag
uv run multi-agentic-rag clean-system-state --system PROJECT_1
uv run multi-agentic-rag ingest-doc "documents\inbox\PROJECT_1\SIIMCS_BRD_V1.pdf" --system PROJECT_1 --version v1
uv run multi-agentic-rag ingest-doc "documents\inbox\PROJECT_1\SIIMCS_BRD_V2.pdf" --system PROJECT_1 --version v2
```

### Phase 1: Turn On Real Local Semantic Retrieval

Goal:

Use BAAI/bge-m3 for real Chroma retrieval instead of hash embeddings.

Implement:

1. Set target local `.env` values:

```text
EMBEDDING_PROVIDER=huggingface
DEFAULT_EMBEDDING_MODEL=BAAI/bge-m3
VECTOR_STORE_PROVIDER=chroma
```

2. Keep tests pinned to hash embeddings through test-specific settings.
3. Add a small embedding smoke test that verifies a Hugging Face embedding call
   can run when target mode is requested.
4. Re-ingest after changing embedding provider because existing Chroma vectors
   were built with hash embeddings.

Validation:

```powershell
uv run multi-agentic-rag doctor
uv run multi-agentic-rag ingest-doc "documents\inbox\PROJECT_1\SIIMCS_BRD_V1.pdf" --system PROJECT_1 --version v1
uv run multi-agentic-rag query "What are the covered areas of BRD V1?" --system PROJECT_1 --version v1
```

Expected proof:

- doctor shows Hugging Face/BGE, not hash.
- ingest output prints BGE provider/model.
- query retrieval sources include vector.

### Phase 2: Promote Neo4j From Traceability To GraphRAG Backbone

Goal:

Make graph retrieval and graph relationships influence answers and test
planning.

Implement:

1. Add graph retrieval templates for explicit version scope:
   - facts by `system_name + version`
   - chunks by `document_id`
   - requirements by `version`
   - requirements linked to protocols, sensors, thresholds, topics, endpoints
2. Update `answer_query()` so `--version v1` can use graph facts.
3. Add graph-backed scope retrieval:
   - `covered_area`
   - `in_scope`
   - `out_of_scope`
   - objective/capability sections
4. Store richer typed entities:
   - Requirement
   - ScopeArea
   - Capability
   - Protocol
   - Sensor
   - Threshold
   - Endpoint
   - Topic
5. Update coverage planning to use graph paths before falling back to SQLite.
6. Record graph path evidence in coverage records and query answers.

Validation:

```powershell
uv run multi-agentic-rag graph-check
uv run multi-agentic-rag query "What are the covered areas of BRD V1?" --system PROJECT_1 --version v1
uv run multi-agentic-rag coverage-plan --system PROJECT_1 --version v1 --count 25 --force
```

Expected proof:

- query output includes `graph` in retrieval sources.
- coverage scenarios are ranked from graph relationships, not just cycled
  templates.
- scope answer excludes table headers and unrelated section fragments.

### Phase 3: Add Optional OpenAI Reasoning With Evidence Gates

Goal:

Use OpenAI only where it improves reasoning, while preserving evidence-gated
answers.

Implement:

1. Add an `LLMClient` interface with providers:
   - none
   - openai
   - azure_openai
2. Add structured task parsing:
   - intent
   - system
   - version
   - count
   - action
   - output preference
3. Add deterministic fallback when `LLM_PROVIDER=none`.
4. Add LLM-backed answer synthesis that can only use retrieved evidence records.
5. Add LLM-backed extraction fallback only after deterministic extraction runs.
6. Require evidence verifier checks:
   - no evidence -> no answer
   - no graph path -> no relationship claim
   - no delta -> no impact claim
   - no requirement link -> no coverage claim

Validation:

```powershell
uv run multi-agentic-rag task "Generate 15 testcases for BRD V1" --system PROJECT_1 --version v1
uv run multi-agentic-rag task "Show me the last test result for BRD V1" --system PROJECT_1 --version v1
```

Expected proof:

- first command generates or reuses 15 scenarios unless `--count` overrides it.
- second command routes to `last_result`, not query.
- answers include citations and do not invent claims.

### Phase 4: Add Domain Profiles And Simulators

Goal:

Move protocol scenarios from blocked placeholders to executable validations.

Implement:

1. Define a domain profile schema:

```text
domain
protocols
fixtures
simulator
real_target
required_config
test_patterns
skip_or_block_policy
```

2. Add simulator config support:

```text
SIMULATOR_CONFIG_PATH=...
GENERATED_TEST_EXECUTION_MODE=simulator
```

3. Implement adapters in this order:
   - REST simulator/client
   - MQTT simulator/client
   - Modbus simulator/client
   - CAN simulator/client
4. Generate pytest fixtures that call adapter APIs instead of only checking
   document-contract fields.
5. Keep real endpoint mode separate from simulator mode.

Validation:

```powershell
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 25 --force
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 25
```

Expected proof:

- REST/MQTT scenarios execute against simulator fixtures.
- missing simulator config still reports BLOCKED.
- configured simulator mode produces PASS/FAIL from actual adapter behavior.

### Phase 5: Improve Scenario Quality And Reports

Goal:

Make generated QA artifacts more useful for client-facing automation work.

Implement:

1. Add a scenario selector that ranks by:
   - requirement criticality
   - protocol risk
   - threshold/boundary behavior
   - changed facts between versions
   - coverage gaps
2. Add coverage categories:
   - happy path
   - boundary
   - negative
   - integration
   - regression
   - traceability
3. Add report generation:
   - Markdown
   - JSON
   - CSV
   - later Excel
4. Store report metadata in SQLite and optionally Neo4j.

Validation:

```powershell
uv run multi-agentic-rag coverage-plan --system PROJECT_1 --version v1 --count 25 --force
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 25
uv run multi-agentic-rag last-results --system PROJECT_1 --version v1
```

Expected proof:

- scenarios are varied and requirement-ranked.
- reports include evidence, graph paths, generated file, run status, and
  blockers.

## Immediate Next Implementation Order

Recommended order:

1. Fix state hygiene and observability:
   - scoped cleanup command
   - command output provider details
   - retrieval source printing
2. Fix task routing bugs:
   - parse `"last test result"`
   - parse numeric counts from natural language
3. Enable graph retrieval for explicit version queries.
4. Turn target mode on:
   - `EMBEDDING_PROVIDER=huggingface`
   - `GRAPHRAG_REQUIRED=true`
   - re-ingest clean `PROJECT_1`
5. Add graph-backed coverage planning.
6. Add optional OpenAI structured task parser and evidence-bounded answer
   synthesizer.
7. Add simulator adapters, starting with REST and MQTT.

## Current Proof Commands To Re-run After Cleanup

Use these after implementing the cleanup command or manually cleaning
`PROJECT_1` state:

```powershell
uv run multi-agentic-rag doctor
uv run multi-agentic-rag graph-check

uv run multi-agentic-rag ingest-doc "documents\inbox\PROJECT_1\SIIMCS_BRD_V1.pdf" --system PROJECT_1 --version v1
uv run multi-agentic-rag ingest-doc "documents\inbox\PROJECT_1\SIIMCS_BRD_V2.pdf" --system PROJECT_1 --version v2

uv run multi-agentic-rag query "What are the covered areas of BRD V1?" --system PROJECT_1 --version v1
uv run multi-agentic-rag coverage-plan --system PROJECT_1 --version v1 --count 25 --force
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 15 --force
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 15
uv run multi-agentic-rag last-results --system PROJECT_1 --version v1

uv run multi-agentic-rag task "Generate 15 testcases for BRD V1" --system PROJECT_1 --version v1
uv run multi-agentic-rag task "Show me the last test result for BRD V1" --system PROJECT_1 --version v1
```

Expected target result after the next implementation pass:

- doctor shows target provider readiness.
- query reports graph/vector/keyword sources.
- task command honors natural-language count.
- last test result task routes correctly.
- V1 coverage does not include V2-as-V1 contaminated evidence.
- protocol tests either execute against configured simulators or report a clean
  BLOCKED status with one non-duplicated blocker reason.
