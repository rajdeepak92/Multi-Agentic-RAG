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

## Strategic Gap Summary

| Gap | Severity | Why it matters | Next action |
| --- | --- | --- | --- |
| LangGraph workflow is coarse-grained | High | Current wrapper delegates to services instead of one node per agent role | Split wrappers into finer functional nodes over time |
| Real protocol adapters missing | High | Generated tests cannot validate live Modbus/MQTT/CAN/REST targets yet | Add mock/simulator adapters first, then real endpoints |
| Domain plugin contract missing | High | Protocol-specific QA cannot scale cleanly | Define domain profile and adapter contract |
| Graph is not the planning backbone yet | High | Relationship claims and test selection need graph paths | Promote graph retrieval into coverage/scenario selection |
| Sidecar schema needs broader domain fields | Medium | v2 exists, but Robot/keyword/simulator fields are still future | Extend after domain profile contract |
| LLM extraction disabled | Medium | Regex extraction has lower recall | Add optional structured fallback after evidence gates |
| Robot Framework not generated | Medium | Keyword-driven execution is future client value | Defer until pytest mock execution is stable |
| Enterprise infrastructure absent | Future | Required for multi-user scale, not local phase | Keep documented as future only |

## Feasibility Conclusion

The architecture is feasible if implemented in stages:

1. Preserve the current local-first evidence pipeline.
2. Make LangGraph the orchestration wrapper before deeper refactors.
3. Strengthen generated pytest with dependency-aware SKIP/BLOCKED behavior.
4. Add graph-backed planning and relationship checks.
5. Add domain profiles and Modbus first.
6. Add optional LLM and Robot layers only after evidence and execution contracts
   are stable.
7. Add enterprise infrastructure after the local QA automation contract works.

This path keeps MARAG practical for local development while aligning the target
architecture with the company goal.
