# MARAG Updated Goal

## Project Definition

MARAG is an Agentic AI-enabled QA automation framework powered by Knowledge
Graph, GraphRAG, domain plugins, reusable test automation generation, pytest
execution, and future Robot Framework keyword mapping.

The framework converts unstructured engineering documents into structured domain
knowledge, then uses that knowledge to plan, generate, validate, execute, and
report QA automation assets.

## Architecture Identity

MARAG should not be presented only as a GraphRAG chatbot.

Correct framing:

```text
Agentic AI-enabled QA automation framework powered by
Knowledge Graph + GraphRAG + Multi-Agent orchestration.
```

GraphRAG is the intelligence layer. It is used to find evidence, graph paths,
domain relationships, requirement links, coverage gaps, and test-relevant
context. The primary outputs are generated QA artifacts and traceability, not
only chat answers.

## Current Supported Task Types

### 1. Document Ingestion

User provides a local document path.

MARAG currently:

- Parses PDF and DOCX documents.
- Chunks text with source metadata.
- Extracts deterministic facts.
- Updates SQLite metadata.
- Updates SQLite FTS5/BM25 keyword search.
- Updates vector storage through Chroma or Weaviate.
- Updates Neo4j when configured and reachable.
- Preserves active and superseded evidence.

Current local file input is enough for package mode. MinIO/S3 is a future
enterprise option, not a current requirement.

### 2. Test Automation Generator

User asks MARAG to generate tests from an ingested feature document.

MARAG currently:

- Selects requirement-linked coverage scenarios.
- Creates generated pytest artifacts under
  `generated/<system>/<brd_version>/`.
- Writes `pytest.ini`, `conftest.py`, pytest class files, and JSON sidecars.
- Validates generated Python syntax with `py_compile`.
- Runs pytest through the MARAG runner.
- Captures pass/fail/skip counts.
- Updates JSON `run_history`.
- Stores execution records in SQLite.

Current generated tests are placeholder-based until real mocks, simulators,
protocol clients, or product interfaces exist. Future generated tests must not
fake external calls. Missing real dependencies must become SKIP or BLOCKED.

### 3. Informative Chatbot

User asks questions about ingested documents.

MARAG should answer only from evidence:

```text
No evidence -> no answer.
No requirement link -> no coverage claim.
No graph path -> no relationship claim.
```

The chatbot remains a supporting workflow for QA engineers and analysts. It is
not the whole product.

## GraphRAG Role

GraphRAG should support:

- Requirement lineage.
- Document version truth.
- Graph paths between requirements, facts, protocols, sensors, devices, tests,
  and coverage.
- Multi-hop relationship and impact reasoning.
- Evidence selection for answers and test generation.
- Traceability from generated tests back to document chunks and facts.

Graph retrieval should be primary for relationship reasoning. Hybrid retrieval
must remain available:

- Graph retrieval for known extracted relationships.
- BM25 for exact IDs, registers, protocols, constants, topics, and sensor names.
- Vector retrieval for semantic similarity and paraphrased facts.
- Metadata lookup for deterministic registry state.

## Generated Automation Role

Generated automation assets are first-class outputs:

- Test scenarios.
- Structured test cases.
- Pytest scripts.
- Future Robot Framework keyword mappings.
- Simulator or mock configuration.
- JSON sidecars.
- Reports.
- Traceability and coverage records.

Pytest is the current execution foundation. Robot Framework is a future
keyword-driven layer after pytest mock/simulator execution is stable.

## Domain Plugin Direction

Target domain plugins:

- Modbus.
- MQTT.
- CAN.
- REST/API.
- Sensors.
- Device protocols.
- Simulator integrations.

Domain plugins should define:

- Extraction rules.
- Domain entities.
- Graph mapping.
- Dependency requirements.
- Test pattern templates.
- Optional simulator or mock behavior.
- Reusable execution keywords.

## Non-Goals For The Current Local Phase

- No production UI/auth.
- No Kubernetes.
- No Docker as a local requirement.
- No MinIO/S3 as a current dependency.
- No mandatory PostgreSQL or OpenSearch.
- No required paid API.
- No fake protocol/device calls.
- No unsupported coverage claims.
