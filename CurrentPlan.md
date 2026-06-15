# Current Implementation Plan: Option-4 Agentic QA Automation Framework

Last updated: 2026-06-12

## 1. Product Definition

MARAG is an Agentic AI-enabled QA automation framework powered by Knowledge
Graph, GraphRAG, and multi-agent orchestration.

It converts unstructured BRD/SRS/design/interface knowledge into graph-backed
domain intelligence, then uses workflow agents to generate, validate, execute,
and report requirement-linked QA automation assets.

GraphRAG is the intelligence layer. The product outputs are:

- Requirement-linked test scenarios.
- Structured coverage records.
- Pytest automation artifacts.
- JSON sidecars and run history.
- Generated Robot Framework wrappers and future Robot execution.
- Future simulator/adapter configuration.
- Coverage, traceability, and execution reports.
- Evidence-grounded answers as a supporting chatbot workflow.

## 2. Current Verified Implementation

The current repository is no longer only a GraphRAG chatbot foundation. It has a
local-first QA automation path with executable pytest generation and tracking.

Verified current behavior:

- PDF and DOCX ingestion.
- Chunking and deterministic fact extraction.
- SQLite registry for documents, chunks, facts, deltas, coverage, generated
  files, and test run results.
- SQLite FTS5/BM25 exact search.
- Chroma local vector fallback.
- Optional Weaviate vector store.
- Hugging Face embedding provider with `BAAI/bge-m3` as the real retrieval
  default.
- Hash embedding fallback for deterministic tests and offline smoke checks.
- Embedding provider/model metadata written into vector records.
- Optional Neo4j graph population for documents, chunks, facts, deltas,
  generated tests, coverage, and test run results.
- Deterministic Neo4j GraphRAG retrieval templates for facts, lineage, deltas,
  related subgraphs, and test traceability.
- Version lifecycle with active/superseded evidence.
- Conservative evidence-grounded query behavior.
- Coverage planning that requires requirement evidence.
- Fine-grained service-backed LangGraph nodes for task routing, generation,
  execution, sidecar checks, DB updates, reporting, and final validation.
- Generated pytest artifacts under `generated/<system>/<brd_version>/`.
- Generated `pytest.ini`, `conftest.py`, class-based pytest file, Robot wrapper,
  and JSON sidecar.
- Sidecar schema `test-automation-tracking.v4`.
- Dependency-aware generated tests:
  - protocol scenarios require mock, simulator, or real endpoint readiness;
  - missing dependencies are SKIP/BLOCKED;
  - explicit mock mode can produce deterministic PASS results;
  - no fake protocol/device PASS.
- `py_compile` validation before pytest execution.
- pytest execution and pass/fail/skip parsing.
- Failure categories:
  - `PROTOCOL_UNAVAILABLE`
  - `DEPENDENCY_MISSING`
  - `GENERATION_ERROR`
  - `ASSERTION_FAILURE`
  - `ENVIRONMENT_ERROR`
- SQLite and JSON sidecar update after each run.

## 3. Non-Negotiable Engineering Rules

- No evidence -> no answer.
- No version -> no truth.
- No delta -> no impact claim.
- No requirement link -> no coverage claim.
- No extracted fact -> no graph edge.
- No graph path -> no relationship claim.
- No real dependency -> SKIP/BLOCKED, not PASS.
- No fake protocol calls.
- No hard delete of generated assets.
- No destructive overwrite without a clear implementation path.
- Generated test code must pass Python syntax validation.
- Generated sidecar JSON must be updated after every run.
- Every generated test must link to requirement evidence.
- Local-first SQLite/Chroma mode must continue to work.
- Docker, Kubernetes, PostgreSQL, OpenSearch, MinIO/S3, production auth, and
  heavy UI are future/optional unless explicitly approved.

## 4. Embedding Decision

| Mode | Tool / Technology | Current Decision |
| --- | --- | --- |
| Primary local/open-source | `BAAI/bge-m3` through Hugging Face | Real retrieval default |
| Test/offline mode | Hash embedding fallback | Deterministic tests and smoke checks only |
| Optional enterprise fallback | Azure OpenAI / OpenAI embeddings | Future governed fallback only |

Current code impact:

- `Settings.default_embedding_model` defaults to `BAAI/bge-m3`.
- `Settings.embedding_provider` defaults to `huggingface`.
- Tests use `embedding_provider="hash"` explicitly.
- `doctor` reports the embedding provider/model and warns when hash is used.
- Chroma and Weaviate records include `embedding_provider` and
  `embedding_model` metadata.

Managed embeddings must not be described as the primary architecture.

## 5. Current End-To-End Flow

### Document Ingestion

1. User provides a local PDF/DOCX path or folder.
2. MARAG validates path, system, and version.
3. MARAG parses text and tables where supported.
4. MARAG chunks evidence with document/version metadata.
5. MARAG extracts deterministic facts.
6. SQLite stores documents, chunks, facts, and deltas.
7. SQLite FTS5/BM25 indexes chunks.
8. Chroma or Weaviate indexes vectors with embedding model metadata.
9. Neo4j mirrors document, chunk, fact, entity, and delta graph nodes when
   reachable.

### Test Automation Generator

1. User asks to generate tests for a system/version.
2. LangGraph workflow wrapper routes the task.
3. Coverage planner selects requirement-linked scenarios.
4. Test generator writes `pytest.ini`, `conftest.py`, pytest class file, Robot
   wrapper, and sidecar JSON.
5. Dependency audit marks each protocol scenario as ready, blocked, mock,
   simulator, real, or document-contract.
6. SQLite stores the generated test file record.
7. Neo4j mirrors generated test and coverage nodes when configured.
8. Runner validates syntax with `py_compile`.
9. Runner executes pytest.
10. Runner classifies PASS/FAIL/SKIP/BLOCKED and failure category.
11. Runner updates SQLite, JSON sidecar run history, and optional Neo4j
    `TestRun` node.

### Informative Chatbot

1. User asks a document question.
2. Retrieval combines graph, vector, keyword, and registry evidence.
3. Answer is generated deterministically from evidence.
4. No evidence means controlled no-answer.

## 6. Current JSON Sidecar Contract

Minimum current fields:

```json
{
  "schema_version": "test-automation-tracking.v4",
  "project": "",
  "system_name": "",
  "document_id": "",
  "document_ids": [],
  "document_version": "",
  "source_document_path": "",
  "source_documents": [],
  "generated_test_file": "",
  "generated_robot_file": "",
  "mock_mode": false,
  "mock_warning": "",
  "domain_profile_ref": "",
  "protocol_adapters": [],
  "simulator_config": {},
  "device_config_required": false,
  "robot_keyword_mapping": [],
  "handoff_summaries": [],
  "scenario_group": "",
  "selected_scenarios": [],
  "requirements": [],
  "extracted_facts_used": [],
  "evidence_refs": [],
  "domain": "",
  "protocols": [],
  "dependency_audit": {
    "status": "",
    "execution_mode": "",
    "pytest_ini": "",
    "conftest": "",
    "fixtures": [],
    "external_dependencies": [],
    "missing_dependencies": []
  },
  "coverage": {
    "coverage_intent": "",
    "covered_requirements": [],
    "coverage_gaps": []
  },
  "run_history": [
    {
      "run_id": "",
      "timestamp": "",
      "command": "",
      "status": "",
      "failure_category": "",
      "failure_reason": "",
      "stdout_path": "",
      "stderr_path": ""
    }
  ],
  "db_update_status": ""
}
```

Future additions should cover adapter versions, promotion metadata, and richer
domain pack references.

## 7. Gap Analysis After Current Update

| Gap | Current State | Severity | Next Action |
| --- | --- | --- | --- |
| Fine-grained LangGraph agent graph | Fine-grained service-backed nodes exist | Medium | Add durable checkpoints and richer conditional edges |
| Evidence verifier | Coverage/query gates exist, but no full claim verifier | High | Add `EvidenceVerifierAgent` over answers and generated tests |
| Domain plugin contract | Protocol detection exists, no plugin packs | High | Add `DomainProfile` and adapter contract |
| Real protocol adapters | Not implemented | High | Add mock/simulator adapters before real endpoints |
| Protocol test pattern library | Generic dependency-aware pytest only | High | Add Modbus/REST/MQTT/CAN patterns |
| Robot Framework execution | Wrapper generated; execution future | Medium | Add after pytest mock path stabilizes |
| Structured LLM extraction | Placeholder/future | Medium | Add guarded Pydantic extraction fallback |
| Reranking | Interface placeholder | Medium | Integrate optional reranker into hybrid retrieval |
| Table-to-fact enrichment | Parser support exists, richer mapping needed | Medium | Add threshold/register/signal table fact extraction |
| Reporting exports | Basic CLI/API output | Medium | Add Markdown/JSON/CSV/Excel-ready reports |
| Enterprise infrastructure | Future only | Future | Keep optional until local QA contract is stable |

## 8. Updated Phase Plan

### Phase 1: Stabilize Current GraphRAG Foundation

Completed in current slice:

- `BAAI/bge-m3` configured as real embedding default.
- Hash embeddings retained for tests.
- Embedding provider/model metadata added to vector records.
- Neo4j ingestion graph writes are implemented.
- Neo4j generated-test, coverage, and test-run graph writes are implemented.
- Graph retrieval can return test traceability paths.

Remaining:

- Add live Neo4j integration smoke test for generated-test lineage when a local
  Neo4j instance is available.
- Add model-version-aware reindex command or diagnostic.

### Phase 2: LangGraph Orchestration And Evidence Verification

Current:

- `handle_task` delegates to service-backed LangGraph workflow wrappers.
- Nodes call existing ingestion, retrieval, coverage, generation, execution,
  and last-result services.

Next:

- Add strict Pydantic workflow state per task type.
- Add node-level structured logging and durable workflow run IDs.
- Split generation into:
  - `DomainAnalyzerAgent`
  - `ScenarioSelectionAgent`
  - `DependencyAuditAgent`
  - `TestHarnessAgent`
  - `TestWriterAgent`
  - `SyntaxValidationAgent`
  - `TestExecutionAgent`
  - `FailureClassifierAgent`
  - `JsonSidecarAgent`
  - `DatabaseUpdateAgent`
- Enforce `EvidenceVerifierAgent` before answer/test output.

### Phase 3: Domain Modeling And Plugin Contract

Next:

- Add domain profile loader.
- Add Modbus first profile unless stakeholders choose another protocol.
- Add unit normalization groundwork.
- Add table-to-fact enrichment for thresholds/registers/signals.
- Add structured LLM extraction only behind evidence/provenance requirements.

### Phase 4: Test Generation Upgrade

Current:

- Generated tests are dependency-aware.
- Explicit mock mode can pass deterministic evidence checks.
- Missing protocol configuration becomes BLOCKED/SKIP.

Next:

- Add protocol pattern library.
- Generate mock/simulator-backed assertions.
- Add adapter readiness checks.
- Add Robot suite and Python keyword library generation after pytest mock path
  is stable.

### Phase 5: Reporting, CI/CD, And Evaluation

Next:

- Add coverage and traceability export reports.
- Add golden RAG evaluation dataset.
- Add optional Ragas/Phoenix/LangSmith evaluation.
- Add CI checks for pytest, generated artifact smoke checks, linting, and type
  checks.

### Phase 6: Enterprise Scale And Governance

Future only:

- PostgreSQL registry and migrations.
- OpenSearch exact search.
- OIDC/OAuth2 and RBAC.
- Persistent audit tables.
- OpenTelemetry.
- Vault/secret manager integration.
- Optional Docker/Kubernetes after explicit enterprise approval.

## 9. What Must Not Be Implemented Yet

- Docker or docker-compose as a local prerequisite.
- Kubernetes.
- MinIO/S3 as a current dependency.
- PostgreSQL or OpenSearch as mandatory runtime services.
- Production auth/RBAC before local workflow stabilization.
- Real device/protocol calls without approved simulator or endpoint config.
- Robot Framework as a required dependency.
- Managed embeddings as the default path.
- Generated artifact commits without an artifact promotion policy.

## 10. Validation Gates

Use these commands from `D:\Multi-Agentic-RAG`:

```powershell
uv sync --locked
uv run pytest -c pyproject.toml tests
uv run multi-agentic-rag doctor
uv run multi-agentic-rag graph-check
uv run multi-agentic-rag ingest-folder "documents\inbox\PROJECT_1" --system PROJECT_1 --version v1
uv run multi-agentic-rag coverage-plan --system PROJECT_1 --version v1 --count 10
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 10
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 10
```

For GraphRAG-required mode, `doctor` and `graph-check` must pass before
claiming graph-backed readiness.
