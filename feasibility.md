# Feasibility: Option-4 Agentic QA Automation Architecture

## Purpose

This document aligns Option-4 with the updated MARAG goal:

```text
Agentic AI-enabled QA automation framework powered by
Knowledge Graph + GraphRAG + Multi-Agent orchestration.
```

GraphRAG is the reasoning layer. Generated QA automation assets, execution
records, reports, coverage, traceability, and evidence-grounded answers are the
framework outputs.

## Feasibility Principles

- Local-first remains the current execution mode.
- Open-source-first remains the default architecture direction.
- Paid APIs are optional and must be configurable.
- Docker, Kubernetes, MinIO/S3, PostgreSQL, OpenSearch, production auth, and
  heavy UI are future options, not current requirements.
- Generated tests must not fake protocol or device calls.
- Missing dependencies must be classified as SKIP or BLOCKED.

## Core Storage And Indexing

| Layer | Current selection | Future option | Purpose | Status |
| --- | --- | --- | --- | --- |
| Knowledge graph | Neo4j | Neo4j managed or enterprise | Store requirements, chunks, facts, entities, graph paths, coverage, tests | Current optional/local; target required for GraphRAG workflows |
| Graph query | Cypher templates | Cypher templates with review controls | Deterministic graph traversal | Current |
| Graph access | Neo4j Python Driver | Same | Python service integration | Current |
| Vector store | Chroma local fallback | Weaviate optional/enterprise | Semantic retrieval | Current Chroma, optional Weaviate |
| Keyword search | SQLite FTS5/BM25 | OpenSearch later | Exact IDs, protocols, constants, registers, topics | Current SQLite, future OpenSearch |
| Metadata registry | SQLite | PostgreSQL later | Documents, chunks, facts, coverage, generated files, execution results | Current SQLite, future PostgreSQL |
| Object artifacts | Local filesystem | MinIO/S3 later | Source copies and parsed artifacts | Current local, future optional |
| Schema contracts | Pydantic | Pydantic plus DB constraints | Typed API and workflow boundaries | Current partial, target stronger |
| Package build | pyproject.toml + uv | Same | Reproducible local package workflow | Current |

## Retrieval And Evidence Pipeline

| Layer | Current selection | Future option | Purpose | Status |
| --- | --- | --- | --- | --- |
| PDF extraction | PyMuPDF | Same | Page-level PDF text extraction | Current |
| DOCX extraction | python-docx | Same | DOCX paragraph/table extraction | Current |
| Table extraction | pdfplumber | Stronger table-to-fact mapping | Thresholds, matrices, register maps | Current parser support; target richer facts |
| OCR fallback | Optional Tesseract | Same | Scanned documents | Optional |
| Chunking | Domain-aware chunker plus LangChain splitters | Richer section/table preservation | Evidence-preserving chunks | Current |
| Information extraction | Deterministic extractors | Optional structured LLM fallback | Requirements, protocols, thresholds, sensors, tests | Current deterministic; LLM future |
| Embeddings | BAAI/bge-m3 | Optional OpenAI/Azure embeddings if approved | Real semantic retrieval | Current config |
| Test embeddings | Hash embedding fallback | Same | Deterministic tests/offline smoke checks | Current test-only |
| Vector retrieval | Chroma or Weaviate | Weaviate scale path | Semantic evidence | Current |
| Keyword retrieval | SQLite FTS5/BM25 | OpenSearch later | Exact engineering lookup | Current |
| Graph retrieval | Neo4j bounded templates | More graph traversal templates | Relationship evidence and lineage | Current basic; target primary |
| Reranking | No-op interface | BAAI/bge-reranker-v2-m3 | Candidate precision | Future |
| Answering | Deterministic evidence rendering | Optional OpenAI/Azure synthesis | Evidence-grounded responses | Current deterministic; LLM future |
| Evidence contract | Pydantic outputs and citations | EvidenceVerifierAgent | Prevent unsupported claims | Current partial; target strict |

## Multi-Agent Workflow And Interfaces

| Layer | Current selection | Target selection | Purpose | Status |
| --- | --- | --- | --- | --- |
| Orchestration | Service-backed LangGraph workflow wrappers | Finer LangGraph agent graph | Stateful workflow control | Current wrapper; target deeper node decomposition |
| CLI | Typer | Typer | Local/operator commands | Current |
| API | FastAPI | FastAPI | Service boundary | Current |
| Agent tools | Python service functions | Controlled tools/nodes | Safe storage/retrieval/generation calls | Current services; target nodes |
| MCP | Placeholder modules | Future MCP tools/resources | External agent access | Future |
| Ingestion agent | Service call | LangGraph node | Parse, chunk, extract, index | Target |
| Domain analyzer | Rule extraction | LangGraph node + domain profiles | Detect Modbus/MQTT/CAN/REST/sensor domains | Target |
| Scenario selector | Coverage planner | LangGraph node | Rank scenarios by evidence and criticality | Target |
| Dependency audit | Dependency-aware audit | Finer LangGraph node | Detect harness, fixture, mock, simulator, real endpoint readiness | Current |
| Test writer | Dependency-aware pytest writer | Pytest mock/simulator-aware writer | Generate maintainable automation | Current scaffold; target stronger |
| Execution agent | Pytest runner through workflow wrapper | Finer LangGraph node | Run tests and capture status | Current |
| Failure classifier | Runner classifier | Finer LangGraph node | PASS/FAIL/SKIP/BLOCKED taxonomy | Current |
| Report generator | CLI/API output | Markdown/JSON/CSV/Excel-ready outputs | Client/CI reporting | Future |

## Domain Knowledge Management

| Layer | Current selection | Target selection | Purpose | Status |
| --- | --- | --- | --- | --- |
| Domain model | Deterministic fact metadata | Domain ontology layer | Normalize protocols, sensors, devices, tests | Future |
| Sensor ontology | Basic sensor extraction | SSN/SOSA-inspired profile | Sensors, observations, units, thresholds | Future |
| Protocol model | Rule patterns | Plugin/profile schema | Modbus, MQTT, CAN, REST semantics | Future |
| Domain registry | SQLite facts | SQLite now, PostgreSQL later | Domain metadata and rules | Future |
| Domain graph | Neo4j typed entities | Richer domain subgraph | Queryable domain relationships | Current basic; target richer |
| Modbus adapter | Extraction only | PyModbus/mock/simulator adapter | Register/coil/polling tests | Future |
| MQTT adapter | Topic extraction only | Topic/payload/broker adapter | Telemetry tests | Future |
| CAN adapter | CAN ID extraction only | Frame/signal adapter | CAN timing and signal tests | Future |
| REST/API adapter | Endpoint extraction only | OpenAPI-aware parser/client | API contract tests | Future |
| Unit normalization | Basic unit strings | Pint or custom unit registry | Correct threshold comparisons | Future |
| Threshold model | Structured facts | Alert/boundary semantics | Boundary coverage and tests | Current facts; target richer |
| Domain packs | None | YAML/JSON packs | Domain onboarding without code rewrites | Future |
| Test pattern library | Generic templates | Protocol-specific templates | Reusable QA generation | Future |

## QA Automation And Execution

| Layer | Current selection | Target selection | Purpose | Status |
| --- | --- | --- | --- | --- |
| Generated framework | pytest | pytest now, Robot future | Test execution | Current pytest |
| Generated structure | `generated/<system>/<brd_version>/` | Same | Runtime artifact isolation | Current |
| Test style | Class-based dependency-aware pytest | Class-based pytest with richer mocks/simulators | Maintainable generated tests | Current scaffold; target stronger |
| Harness | Generated `pytest.ini` and `conftest.py` | Reusable fixtures/hooks/addopts | Stable execution context | Current |
| Sidecar | JSON tracking file | Versioned JSON schema | Traceability and run ledger | Current; target stricter |
| Syntax validation | py_compile | Same | Catch generation errors | Current |
| Execution | pytest runner | pytest plus future Robot | Run generated assets | Current pytest |
| Failure behavior | PASS/FAIL/SKIP/BLOCKED plus categories | Same plus richer reports | Honest status reporting | Current |
| Real protocols | Not implemented | Mock/simulator first, real endpoints later | Device/protocol validation | Future |
| CI reporting | Not implemented | CI/CD reports later | Team automation feedback | Future |

## Governance And Operations

| Layer | Current selection | Future option | Purpose | Status |
| --- | --- | --- | --- | --- |
| Unit tests | pytest | pytest with coverage gates | Quality control | Current |
| API tests | FastAPI TestClient/httpx | Contract tests | Service validation | Current partial |
| Linting | Ruff configured | CI enforced | Style and correctness | Future enforcement |
| Type checking | mypy configured | CI enforced | Interface stability | Future enforcement |
| Logging | Python logging | JSON logs and tracing | Debuggability | Current basic |
| Tracing | None | OpenTelemetry later | Workflow observability | Future |
| RAG evaluation | None | Golden datasets/Ragas/Phoenix later | Retrieval quality | Future |
| Secrets | `.env` local | Vault/secret manager later | Credential safety | Future |
| Auth | None | OIDC/OAuth2 and RBAC later | Multi-user security | Future |
| Audit | SQLite result records/logs | Audit tables/export later | Compliance | Future |
| CI/CD | Local scripts/tests | GitHub Actions/Azure DevOps later | Release confidence | Future |
| Deployment | Local Python | Optional containers/Kubernetes later | Production operations | Future optional |

## Strategic Gap Summary: Blocked Work Requiring Action

This section identifies gaps that are currently **blocked and require deliberate action** to progress.
Future/optional items are documented separately below.

### Blocked Gaps (Must Resolve)

| Gap | Severity | Current State | Why it matters | Acceptance Criteria | Next action |
| --- | --- | --- | --- | --- | --- |
| LangGraph orchestration is coarse-grained | High | Service-backed wrappers delegate to Python functions; single workflow invocation | Cannot test agent routing, state persistence, conditional branching, error recovery, or parallel execution without proper nodes | Each agent role (IntentRouter, DocumentResolver, ScenarioSelector, etc.) is a distinct LangGraph node with explicit state transitions | Refactor workflows.py to use `@graph_node` decorator or `StateGraph.add_node()` for each agent; compile into subgraph |
| Real protocol adapters missing | High | Extraction only: Modbus registers/coils, MQTT topics, CAN IDs, REST endpoints extracted from text; no client/simulator | Tests cannot validate protocol behavior, timing, or data transformation; all protocol scenarios blocked/skipped without mock | Mock adapters exist for Modbus (register read/write), MQTT (pub/sub), CAN (frame send/receive), REST (HTTP GET/POST) with injectable responses; real adapters designed | Design adapter contract in DOMAIN_PLUGIN_STRATEGY.md; implement mock adapters in src/multi_agentic_rag/adapters/; update DependencyAuditAgent |
| Domain plugin contract missing | High | No domain ontology, packs, or profiles; no structured protocol metadata | Protocol-specific QA logic cannot scale without package-able domain definitions; each new protocol requires code changes | Domain profiles (YAML/JSON) define protocol, sensors, thresholds, units, simulator config, test patterns; domain packs installable and referenceable by name | Write DOMAIN_PLUGIN_STRATEGY.md; define domain profile schema; create siimcs_modbus.yaml example domain pack |
| Graph is not the planning backbone | High | Neo4j optional; coverage planning uses SQLite FTS5 primarily; graph retrieval basic | Cannot detect requirement dependencies, impact of version changes, or lineage without traversing relationships | Graph queries power scenario selection: requirement -> affected thresholds -> affected tests; coverage gaps identified by missing paths; version impact shown via SUPERSEDES edges | Implement graph-backed scenario selector; promote graph retrieval in coverage planner; create Cypher templates for impact analysis |
| Report generator not implemented | High | CLI outputs text; no structured artifacts | Cannot produce compliance/audit/traceability reports; no CI/CD reporting or evidence export | Report agent generates Markdown summary, JSON export (requirements x tests matrix), coverage heatmap, traceability graph, failure classification | Implement ReportGeneratorAgent in agents/nodes.py; add report generation to test execution agent; expose as /reports API endpoint |
| Sidecar schema lacks domain and adapter fields | Medium | v3 exists with workflow/run_history/dependency_audit; missing protocol/simulator/keyword/adapter metadata | Cannot track which protocol/simulator was used; cannot map to Robot keywords; cannot detect stale test adapters | v4 schema extends with: protocol_adapters[], simulator_config, robot_keyword_mapping, domain_profile_ref, adapter_versions | Extend JSON sidecar schema; update JsonSidecarAgent; add domain profile reference after domain contract ready |
| Robot Framework mapping not implemented | Medium | Optional scaffold only; no keyword mapping or .robot generation | Keyword-driven/RPA platforms cannot reuse pytest logic; no Robot execution path | RobotMappingAgent maps pytest assertions to Robot keywords; generates .robot files with BDD structure; supports keyword libraries | Implement RobotMappingAgent after pytest mock execution stable; use pytest AST to extract test logic; map to domain-specific keywords |
| Test writer generates scaffold-quality tests | Medium | Tests use mock/block validation; evidence-derived assertions only; no protocol mocking frameworks | Tests do not effectively validate protocol behavior; cannot exercise edge cases or error conditions | Tests use unittest.mock for MQTT/REST; pymodbus mock server for Modbus; pyvisa simulator for instruments; assertions match protocol contracts | Strengthen TestCodeWriterAgent with mock object injection; add protocol-specific assertion libraries; implement error/boundary case generation |

### Non-Blocked Items (Future/Optional)

These items are documented as future-phase work and do not block current framework use:

- **LLM extraction fallback** — Deterministic extraction works; optional LLM fallback deferred after evidence gates stable
- **Enterprise infrastructure** — PostgreSQL, OpenSearch, MinIO/S3, production auth, Kubernetes explicitly deferred to multi-user phase
- **Advanced tracing and observability** — OpenTelemetry, comprehensive audit logging future
- **CI/CD integration** — GitHub Actions, Azure DevOps reporting future; local pytest execution sufficient for Phase 1
- **Production UI and API auth** — FastAPI auth, web UI deferred until multi-tenant architecture decided

## Feasibility Conclusion

The architecture is **feasible and practical** if blocked gaps are resolved in proper order:

### Phase 1 Completion (Current State)

The framework currently supports all local-first operations:

- ✓ Document ingestion with version lifecycle and delta tracking
- ✓ SQLite/Chroma-based retrieval without external services
- ✓ Deterministic coverage planning and test generation
- ✓ Pytest execution with dependency-aware blocking
- ✓ Evidence-grounded traceability (no fake PASS)
- ✓ CLI and FastAPI interfaces

Generated tests **block missing protocol dependencies** instead of faking them.

### Phase 2 Implementation Sequence (Blocked gaps → Unblocked)

1. **Resolve LangGraph workflow coarse-graining** (1-2 weeks)
   - Decompose service wrappers into SubGraph nodes
   - Add explicit state transitions and error handlers
   - Enable proper agent routing and conditional execution
   - Unlock: Stronger orchestration, routing tests, conditional paths

2. **Define domain plugin contract** (1 week)
   - Write DOMAIN_PLUGIN_STRATEGY.md with schema
   - Create siimcs_modbus.yaml as first domain pack
   - Document protocol adapter interface
   - Unlock: Scalable protocol support, reusable domain packs

3. **Implement mock protocol adapters** (2-3 weeks)
   - Modbus mock register server (pymodbus.simulators)
   - MQTT mock broker (paho-mqtt test fixtures)
   - REST mock server (httpx with mock transport)
   - CAN mock interface (can.interfaces.virtual)
   - Update DependencyAuditAgent to recognize mock mode
   - Unlock: Protocol-specific test generation and execution

4. **Promote graph as planning backbone** (1-2 weeks)
   - Implement graph-backed scenario selector
   - Create impact analysis Cypher templates
   - Integrate into coverage planner
   - Unlock: Requirement lineage, version impact detection

5. **Implement report generator** (1 week)
   - ReportGeneratorAgent with Markdown/JSON output
   - Coverage heatmap, traceability matrix, execution summary
   - CI/CD artifact export
   - Unlock: Compliance reporting, audit trails

6. **Strengthen test writer** (1-2 weeks, parallel with adapters)
   - Protocol-specific mock object injection
   - Real assertion libraries (unittest.mock, pymodbus stubs, etc.)
   - Edge case and error scenario generation
   - Unlock: Meaningful test execution beyond blocking

7. **Extend sidecar schema and implement Robot mapping** (1 week each, after domain contract ready)
   - v4 JSON sidecar with domain/adapter/keyword fields
   - RobotMappingAgent for pytest-to-Robot keyword mapping
   - Unlock: RPA/keyword-driven platform compatibility

### Why This Order

- **LangGraph first**: Enables proper testing and debugging of downstream phases
- **Domain + adapters early**: Prevents rework; unblocks test generation for multiple protocols
- **Graph + reports**: Provides traceability and compliance artifacts
- **Robot mapping last**: Depends on pytest stability; adds client value without breaking existing flow

### Risk Mitigation

- Keep deterministic extraction and local-first execution throughout
- Maintain backward compatibility with existing generated tests
- All new components use optional configuration; fallback to Phase 1 behavior if missing
- Test each phase with existing PROJECT_1 BRD examples

### Acceptance Criteria Per Phase

**Phase 2 Complete** when:

- [ ] All 8 blocked gaps resolved with unit/integration tests passing
- [ ] LangGraph nodes compile and route correctly with 95% success rate
- [ ] Mock Modbus/MQTT/CAN/REST adapters exist and pass adapter contract tests
- [ ] Domain pack schema validates and loads correctly
- [ ] Graph impact queries return correct transitive relationships
- [ ] Report generator produces valid Markdown/JSON exports
- [ ] Test writer generates and executes non-blocked tests with real assertions
- [ ] Project_1 BRD v1/v2 workflow produces comparable or better results than Phase 1
- [ ] README and docs updated to reflect new capabilities
- [ ] All existing tests pass; no regressions

See LANGGRAPH_ORCHESTRATION_PLAN.md, DOMAIN_PLUGIN_STRATEGY.md, and TEST_AUTOMATION_STRATEGY.md for detailed implementation guidance.
