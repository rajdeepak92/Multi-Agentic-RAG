# MARAG Strategic Update Plan

## 1. Executive Summary

MARAG is being repositioned from a local-first document RAG framework into an
Agentic AI-enabled QA automation framework powered by Knowledge Graph,
GraphRAG, domain plugins, and multi-agent orchestration.

The exact problem being solved:

- Convert unstructured BRD, SRS, design, interface, and protocol documents into
  structured, graph-backed domain knowledge.
- Use that knowledge to generate, validate, execute, classify, and report QA
  automation assets.
- Preserve evidence, version lineage, requirement links, generated artifacts,
  execution results, and coverage records so engineering claims are auditable.

Primary users:

- QA engineers.
- Future users: test architects, automation engineers, domain SMEs, product
  analysts, and validation leads.

Primary workflows:

1. Document ingestion.
2. Test automation generation and execution.
3. Evidence-grounded informative chatbot.

Architecture identity:

MARAG is an Agentic AI-enabled QA automation framework. GraphRAG is the
intelligence and reasoning layer inside the framework, not the final product by
itself.

The current strongest capability is the local-first evidence pipeline:
PDF/DOCX ingestion, deterministic extraction, SQLite registry, BM25 keyword
retrieval, Chroma vector fallback, optional Weaviate and Neo4j, version
lifecycle tracking, conservative querying, coverage planning, generated pytest
artifacts, JSON sidecars, py_compile validation, pytest execution, and SQLite
result persistence.

The largest gaps are:

- LangGraph workflow wrappers exist, but they are still coarse-grained and
  delegate to deterministic services.
- Generated tests are dependency-aware, but they do not yet exercise real
  mocks, simulators, protocol clients, or product interfaces.
- Domain plugin contracts are not implemented.
- Graph writes exist, but graph-backed retrieval, coverage, and test planning
  are not yet the primary execution backbone.

## 2. Current State

Built today:

- PDF and DOCX ingestion from local file paths.
- Chunking with document, system, version, page, hash, and status metadata.
- Deterministic extraction for requirements, sensors, thresholds, protocols,
  devices, MQTT topics, REST endpoints, CAN identifiers, Modbus registers, and
  test references where rule coverage exists.
- SQLite registry for documents, chunks, facts, deltas, coverage runs,
  generated files, and test execution results.
- SQLite FTS5/BM25 keyword search for exact engineering terms.
- Chroma local vector fallback.
- Optional Weaviate vector backend.
- Optional Neo4j graph indexing; ingestion writes graph data when Neo4j is
  reachable and can be configured as required with `GRAPHRAG_REQUIRED=true`.
- Version lifecycle with active and superseded evidence.
- Deterministic delta records.
- Conservative evidence-gated querying.
- Requirement-linked coverage planning.
- FastAPI and Typer CLI boundaries.
- Generated pytest assets under `generated/<system>/<brd_version>/`.
- Generated `pytest.ini`, `conftest.py`, pytest class files, and JSON sidecars.
- Python syntax validation through `py_compile`.
- Pytest execution through the MARAG runner.
- Sidecar `run_history` updates and SQLite test result records.
- Natural-language task routing for query, coverage, generation, execution,
  and last-result lookup.

Not built today:

- Fine-grained LangGraph orchestration for every workflow step.
- LLM-backed structured extraction.
- LLM-backed final answer synthesis.
- A strict evidence verifier for every generated claim.
- Real Modbus, MQTT, CAN, REST, device, simulator, or product-interface test
  execution.
- Domain profile packs and plugin contracts.
- Robot Framework keyword or suite generation.
- Production MCP server.
- Production UI, auth, RBAC, OIDC, audit export, PostgreSQL, OpenSearch,
  MinIO/S3, or deployment automation.

## 3. Target State

Target definition:

MARAG ingests BRD/SRS/design/interface/protocol documents, converts them into
graph-backed domain knowledge, then uses multi-agent workflows to generate
evidence-linked scenarios, structured test cases, pytest scripts, future Robot
Framework keyword mappings, simulator configurations, reports, traceability,
coverage records, and evidence-grounded answers.

Target architectural roles:

| Area | Target role |
| --- | --- |
| Knowledge Graph + GraphRAG | Domain intelligence, lineage, and multi-hop reasoning |
| LangGraph | Stateful orchestration for ingestion, retrieval, generation, execution, and reporting |
| Hybrid retrieval | Graph for relationships, BM25 for exact terms, vector retrieval for semantic fallback |
| Domain plugins | Protocol, sensor, device, simulator, and interface-specific interpretation |
| Pytest | Current generated execution foundation |
| Robot Framework | Future keyword-driven execution layer |
| JSON sidecars | Portable generated-asset and run-history ledger |
| SQLite | Current local metadata registry |
| PostgreSQL | Future enterprise registry |
| Chroma | Local vector fallback |
| Weaviate | Optional production vector backend |
| OpenSearch | Future large-scale BM25 backend |
| FastAPI | Service/API boundary |
| Typer CLI | Local operator and automation boundary |
| MCP | Future external agent/tool boundary |

Evidence rules:

```text
No evidence -> no answer.
No document path -> no ingestion.
No version -> no truth.
No delta -> no impact claim.
No requirement link -> no coverage claim.
No extracted fact -> no graph edge.
No graph path -> no relationship claim.
No real dependency -> SKIP/BLOCKED, not PASS.
```

## 4. Gap Matrix

| Area | Current state | Target state | Priority |
| --- | --- | --- | --- |
| LangGraph orchestration | Service-backed workflow wrappers route current services | Finer LangGraph workflows own each ingest, query, generation, execution, reporting step | High |
| GraphRAG backbone | Neo4j writes exist for ingestion and generated-test traceability when reachable; graph retrieval has bounded templates | Graph retrieval drives relationship reasoning, coverage, and scenario selection | High |
| Test generation | Dependency-aware pytest scaffolds validate traceability and block missing protocol dependencies | Tests use richer mocks/simulators, meaningful protocol assertions, and real adapters where configured | High |
| Dependency audit | Current audit checks harness and protocol/simulator/endpoint readiness | Audit also checks reusable adapter packages, simulator configs, credentials, and keyword libraries | High |
| JSON sidecar | v2 sidecar tracks scenarios, harness, audit, retry, evidence refs, coverage, DB update, and run history | Sidecar adds fact IDs, Robot keyword mappings, simulator config, and promotion metadata | Medium |
| Domain plugins | Rule extraction knows domain terms; no plugin contract | Modbus, MQTT, CAN, REST/API, sensor, simulator profile packs and Python adapter contract | High |
| Evidence verification | Query path is conservative; generated claims are not centrally verified by an agent | EvidenceVerifierAgent rejects unsupported answer, scenario, coverage, and test claims | High |
| LLM extraction and synthesis | Disabled placeholder interface | Optional structured extraction and answer phrasing behind evidence, schema, and confidence gates | Medium |
| Reranking | No-op reranker interface exists | BGE reranker or equivalent ranking layer after hybrid retrieval | Medium |
| Robot Framework | Not generated | Future keyword mapping and suite generation only after pytest mock execution is stable | Medium |
| Enterprise storage | SQLite local registry | PostgreSQL later, with migrations and audit tables | Future |
| Enterprise search | SQLite FTS5 local BM25 | OpenSearch later for scale | Future |
| Production security | No auth | OIDC/OAuth2 and RBAC later | Future |
| Object storage | Local filesystem | MinIO/S3 optional future backend, not current dependency | Future |
| Deployment | Native local Python | Docker/Kubernetes only as separately approved future deployment track | Future |

## 5. Conflict Analysis

- Do not describe MARAG as only a GraphRAG chatbot. The chatbot is one
  supported task; QA automation generation is the primary direction.
- Do not describe GraphRAG as the final output. GraphRAG is the intelligence
  layer used to produce test assets, reports, coverage, and answers.
- Do not treat MinIO/S3 as current architecture. Local file paths and local
  filesystem object storage are sufficient for current package mode.
- Do not make managed embeddings mandatory. `BAAI/bge-m3` is the primary
  open-source real-retrieval model; hash embeddings are test-only; OpenAI/Azure
  embeddings are optional if approved.
- Do not make Docker a current setup requirement.
- Do not claim real protocol/device automation exists. Current generated tests
  are placeholder-based until mocks, simulators, or endpoints exist.
- Do not claim fine-grained LangGraph agents own every substep yet. Current code
  uses service-backed workflow wrappers while deterministic services do the
  detailed work.
- Do not mark missing real protocol/device dependencies as PASS in future
  generated tests. Missing dependencies must become SKIP or BLOCKED.

## 6. Implementation Roadmap

### Phase 0: Documentation And Contract Alignment

Goal: Align project identity and planning artifacts before more code work.

Work:

- Create `UPDATED_GOAL.md`, `EXECUTION_FLOW.md`,
  `TEST_GENERATION_STRATEGY.md`, `ARCHITECTURE_TARGET.mermaid`, and
  `feasibility.md`.
- Update `README.md` project definition.
- Keep current-state docs conservative about built vs planned behavior.
- Record open questions and implementation defaults.

Acceptance:

- Docs present MARAG as an Agentic QA automation framework.
- Docs clearly separate current local behavior from target/future behavior.
- No doc requires Docker, MinIO/S3, PostgreSQL, OpenSearch, managed embeddings,
  production auth, or real device integration for current local use.

### Phase 1: LangGraph Wrapper And Sidecar Contract

Goal: Move current deterministic services behind observable LangGraph workflow
wrappers without rewriting the internals first.

Work:

- Define Pydantic state models for ingest, query, coverage, generation,
  execution, reporting, and error states.
- Implement functional nodes that call existing services:
  `IntentRouterAgent`, `DocumentResolverAgent`, `IngestionAgent`,
  `DomainAnalyzerAgent`, `ScenarioSelectionAgent`,
  `DependencyAuditAgent`, `TestHarnessAgent`, `TestWriterAgent`,
  `SyntaxValidationAgent`, `TestExecutionAgent`, `FailureClassifierAgent`,
  `JsonSidecarAgent`, `DatabaseUpdateAgent`, `ChatAnswerAgent`, and
  `ReportGeneratorAgent`.
- Keep CLI/FastAPI commands stable while adding workflow wrappers.
- Tighten JSON sidecar schema and add sidecar validation before DB update.
- Extend failure classification names to PASS, FAIL, SKIP, BLOCKED,
  GENERATION_ERROR, ENVIRONMENT_ERROR, ASSERTION_FAILURE, and
  PROTOCOL_UNAVAILABLE.

Acceptance:

- Current CLI/API commands continue to work.
- A workflow run records node start, node end, status, and failure reason.
- Generated sidecars conform to the documented schema.
- Current tests still pass.

### Phase 2: Graph-Backed Planning And Dependency-Aware Pytest

Goal: Make graph-backed evidence and dependency-aware execution the normal
test-generation foundation.

Work:

- Promote graph-backed retrieval into coverage and scenario selection.
- Add graph links for generated tests and execution records where supported.
- Implement dependency audit for protocol mocks/simulators/adapters.
- Generate tests that use deterministic mocks/simulators when configured.
- If required dependencies are unavailable, generate SKIP/BLOCKED behavior
  instead of fake PASS.
- Add graph path checks for relationship claims.

Acceptance:

- No generated scenario claims coverage without requirement evidence.
- No generated relationship claim is made without a graph path or explicit
  source evidence.
- Missing MQTT/Modbus/CAN/REST/simulator dependencies produce SKIP/BLOCKED.
- Pytest files still pass syntax validation before execution.

### Phase 3: Domain Plugin Foundation

Goal: Add a reusable domain profile and adapter model.

Work:

- Define domain profile packs in YAML/JSON.
- Define a Python adapter contract for domain plugins.
- Implement Modbus first as the reference domain.
- Add sensor threshold and unit normalization strategy.
- Add MQTT, CAN, REST/API, and simulator profiles incrementally.
- Store provenance and confidence metadata for rule, table, graph, LLM, and user
  input facts.

Acceptance:

- DomainAnalyzerAgent can identify a domain and load the matching profile.
- Modbus profile can map extracted facts to graph nodes and test patterns.
- Low-confidence or inferred facts route to review before final automation.

### Phase 4: Optional LLM Assistance And Robot Mapping

Goal: Add optional AI assistance without weakening evidence gates.

Work:

- Add structured LLM extraction only as a fallback with Pydantic schemas,
  temperature 0, source chunk references, and confidence/provenance fields.
- Add optional answer synthesis from verified evidence.
- Add optional scenario phrasing and failure-debug suggestions.
- Prototype Robot Framework keyword mapping after pytest mock execution is
  stable.

Acceptance:

- Unsupported LLM claims are rejected.
- Every generated answer and scenario has evidence references.
- Robot output is generated only when keyword mappings exist.

### Phase 5: Enterprise Hardening

Goal: Prepare production options after the local evidence and automation
contract is stable.

Work:

- PostgreSQL registry and migrations.
- OpenSearch BM25 indexing.
- Optional MinIO/S3 object store.
- OIDC/OAuth2 and RBAC.
- Audit tables and compliance export.
- CI/CD checks, reporting, and observability.
- Docker/Kubernetes only if explicitly approved as an enterprise deployment
  track.

Acceptance:

- Enterprise backends are optional and do not break local-first mode.
- CI gates test ingestion, retrieval, graph writes, test generation, execution
  tracking, and docs.

## 7. Implementation Sequencing

Recommended sequence:

1. Documentation and contract alignment.
2. Sidecar schema validation and failure taxonomy.
3. LangGraph wrappers around current deterministic services.
4. Graph-backed retrieval and planning improvements.
5. Dependency audit and SKIP/BLOCKED execution behavior.
6. Modbus domain profile and simulator/mock adapter.
7. Optional LLM extraction/synthesis behind evidence checks.
8. Robot Framework keyword mapping prototype.
9. Enterprise backends and security.

## 8. Testing Strategy

Test layers:

- Unit tests for sidecar schema, failure classification, dependency audit,
  domain profiles, and state transitions.
- Integration tests for ingest -> coverage -> generate -> run -> last-results.
- Graph tests for document -> chunk -> fact -> requirement -> test lineage.
- Retrieval tests for graph, BM25, vector, and registry evidence merging.
- Generated-test tests for `py_compile`, pytest execution, BLOCKED/SKIP
  classification, and `run_history`.
- API tests for documents, query, coverage, tasks, tests, doctor, and health.
- CLI smoke tests for `doctor`, `graph-check`, `generate-tests`,
  `run-testcases`, and `last-results`.

Validation commands:

```powershell
uv run pytest -c pyproject.toml tests
uv run multi-agentic-rag doctor
uv run multi-agentic-rag graph-check
uv run multi-agentic-rag validate-real-brd
```

`validate-real-brd` requires `SIIMCS_BRD_V1.pdf` and `SIIMCS_BRD_V2.pdf` at the
expected repo-root paths. If those files are absent, the validation failure is
an environment/input condition.

## 9. Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| LLM hallucination | Unsupported answers or generated scenarios | Keep LLM optional, structured, source-linked, and behind EvidenceVerifierAgent |
| LangGraph rewrite risk | Breaks working CLI/API flows | Wrap current services first, then refactor internals incrementally |
| Fake test success | Manager/client may trust invalid automation | Missing real dependencies must produce SKIP/BLOCKED, not PASS |
| Graph dependency failures | GraphRAG workflow cannot run | Keep `doctor` and `graph-check`; document offline local fallback clearly |
| Domain scope creep | Protocol adapters become too broad | Implement Modbus first, then expand |
| Enterprise infrastructure drift | Local-first workflow breaks | Keep PostgreSQL/OpenSearch/MinIO/auth/Docker optional future tracks |
| Dirty generated assets | Existing generated files get overwritten unexpectedly | No hard delete; regenerate only with force or validated stale artifact handling |

## 10. What Should Not Be Implemented Yet

- Full enterprise auth.
- Kubernetes.
- Docker or docker-compose as current workflow.
- MinIO/S3 as current dependency.
- Full OpenSearch production deployment.
- PostgreSQL migration unless Phase 5 starts.
- Real device integration without simulator/protocol endpoints.
- Heavy UI.
- Production MCP server.
- Robot Framework as required output.
- Managed embeddings as required dependency.
- LLM-only extraction or generation without evidence checks.

## 11. Open Questions

1. Should generated tests target pytest only in Phase 1, or pytest + Robot
   Framework?
2. Should Robot Framework be a Phase 2 execution layer or only future keyword
   mapping?
3. What protocol will be validated first: Modbus, MQTT, CAN, REST, or
   simulator-only?
4. Will test execution be real-device, simulator, mock, or hybrid?
5. Should generated tests execute automatically or require manual approval
   first?
6. What is the expected document volume for the first demo?
7. Should graph population become mandatory in Phase 2?
8. Should OpenAI be used for scenario selection now, or remain optional?
9. Should generated tests be committed to repo or kept in generated runtime
   folder only?
10. Should DB update happen before or after generated JSON sidecar validation?
