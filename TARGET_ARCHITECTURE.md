# MARAG Target Architecture

## Identity

MARAG is an Agentic AI-enabled QA automation framework powered by Knowledge
Graph, GraphRAG, multi-agent orchestration, and reusable automation execution
assets.

It is not only a chatbot. It is not only a document RAG system. The target user
workflow is:

```text
QA engineer provides BRD/SRS/design/interface documents
-> MARAG ingests and versions evidence
-> MARAG extracts facts and domain entities
-> MARAG plans coverage through GraphRAG
-> MARAG generates pytest artifacts now
-> MARAG emits Robot Framework wrappers beside generated pytest assets
-> MARAG executes or prepares execution honestly
-> MARAG stores results, coverage, traceability, and artifact paths
```

## Mode Strategy

Default mode remains local-first:

- SQLite registry.
- SQLite FTS5/BM25.
- Chroma vectors.
- Hash embeddings.
- Deterministic extraction and answer rendering.
- Optional Neo4j.
- Optional LLMs.
- Pytest-first generated execution.

Target GraphRAG mode is explicit:

```powershell
uv run multi-agentic-rag doctor --target-graphrag --system PROJECT_1 --version v1
```

Target mode requires:

- Neo4j connectivity and graph population.
- `BAAI/bge-m3` embeddings.
- `BAAI/bge-reranker-v2-m3` reranker.
- OpenAI Responses client.
- REST/MQTT simulator readiness.
- Graph evidence for GraphRAG query and scenario planning.

## Knowledge Intelligence Layer

Responsibilities:

- Parse PDF/DOCX documents.
- Preserve page/chunk/document lineage.
- Extract deterministic facts.
- Run optional evidence-gated LLM fallback extraction.
- Normalize requirement, threshold, sensor, protocol, endpoint, topic, and test
  facts.
- Store documents, chunks, facts, deltas, coverage, generated files, and results.
- Maintain active/superseded lifecycle state.
- Retrieve with graph, vector, keyword, and metadata paths.
- Reject unsupported answers.

Current technologies:

- PyMuPDF, pdfplumber, python-docx.
- LangChain text splitters.
- SQLite and SQLite FTS5.
- Chroma.
- Optional Weaviate.
- Optional Neo4j.
- Optional OpenAI/Azure OpenAI.
- Optional BGE embeddings and reranking.

## Agentic Reasoning Layer

Current orchestration is service-backed LangGraph. The target architecture keeps
the services but decomposes orchestration into explicit agent nodes:

- `IntentRouterAgent`
- `DocumentResolverAgent`
- `IngestionAgent`
- `VersionDeltaAgent`
- `DomainAnalyzerAgent`
- `CoverageAnalyzerAgent`
- `ScenarioSelectionAgent`
- `DependencyAuditAgent`
- `TestHarnessAgent`
- `TestWriterAgent`
- `RobotMappingAgent`
- `SyntaxValidationAgent`
- `TestExecutionAgent`
- `FailureClassifierAgent`
- `JsonSidecarAgent`
- `DatabaseUpdateAgent`
- `EvidenceVerifierAgent`
- `ReportGeneratorAgent`
- `FinalRouterValidationAgent`

The LLM is the planner/brain only when configured. Python agents remain the
tools that mutate files, databases, graph state, and runtime artifacts.

## Automation Execution Layer

Current execution:

- Generated pytest class files.
- Generated `pytest.ini`.
- Generated `conftest.py`.
- Generated JSON sidecar.
- Generated coverage report JSON.
- Generated Robot mapping wrapper.
- JUnit XML report from pytest execution.
- SQLite and optional Neo4j execution trace.

Future execution:

- Robot Framework execution.
- Protocol-specific keyword libraries.
- Modbus, MQTT, CAN, and REST simulator adapters.
- Safe real endpoint/device execution when explicitly configured.
- CI reports and coverage dashboards.

## Hybrid Retrieval Position

Graph-only retrieval is not enough:

- Graph answers relationship and lineage questions.
- BM25 answers exact IDs, endpoints, topics, registers, constants, and protocol
  strings.
- Vector retrieval finds semantically related evidence.
- Metadata queries enforce version and active/superseded truth.

Target GraphRAG mode requires graph evidence, but the strongest retrieval
contract remains hybrid and evidence-gated.

## Non-Goals For Current Phase

- Mandatory Docker/Kubernetes.
- Mandatory OpenAI/Azure.
- Mandatory Hugging Face model downloads.
- Mandatory Neo4j for local developer flow.
- Mandatory Weaviate/OpenSearch/PostgreSQL/MinIO.
- Mandatory Robot execution.
- Large UI.
- Full production auth/RBAC.
