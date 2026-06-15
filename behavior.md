# MARAG Test-Automation Generator Behavior

This document records the current behavior achieved for MARAG as of this
implementation pass. It is intentionally conservative and only describes what is
now represented in code.

## Current Goal

MARAG can act as a document-grounded, dependency-aware test-automation code
generator. It creates pytest artifacts from evidence and marks protocol/device
dependency gaps as blocked or skipped instead of faking external calls.

The current supported task categories are:

1. Ingest a document and keep local stores up to date.
2. Generate dependency-aware pytest automation artifacts from BRD evidence.
3. Answer informative questions from ingested document evidence.

For the target-state roadmap beyond this current behavior, see
`STRATEGIC_UPDATE_PLAN.md`, `UPDATED_GOAL.md`, `EXECUTION_FLOW.md`, and
`TEST_GENERATION_STRATEGY.md`.

## Coverage Planning Source

Coverage/scenario planning now prefers the Neo4j knowledge graph when graph
evidence is available.

Current behavior:

- Ingestion writes document, chunk, fact, entity, and delta records to Neo4j
  when Neo4j is reachable.
- `coverage-plan`, `generate-tests`, `run-testcases`, and natural-language
  testcase tasks call the same coverage planner.
- The coverage planner queries Neo4j for requirement facts for the requested
  `system/version`.
- Scenario selection is built from the Neo4j-selected requirement facts.
- SQLite registry records are still used to attach durable evidence text, chunk
  IDs, document IDs, versions, and source hashes.
- If Neo4j is unavailable in local mode, MARAG falls back to SQLite registry
  facts and reports that graph-backed scenario selection was unavailable.
- In target GraphRAG mode, missing Neo4j graph evidence blocks planning instead
  of silently falling back.

The coverage reuse scope includes the planning source and selected fact IDs, so
old SQLite-only coverage runs are not silently reused once graph-backed
selection is available.

## Test-Automation Generation Flow

The testcase generation path follows this agent-style handoff:

1. `IntentRouter`
2. `DocumentResolver`
3. `EvidenceCollector`
4. `ScenarioSelector`
5. `TestPlanAgent`
6. `DependencyAuditAgent`
7. `HarnessAgent`
8. `TestCodeWriterAgent`
9. `PytestValidationAgent`
10. `ExecutionAgent`
11. `FailureDebuggerAgent`
12. `TrackingJsonAgent`
13. `DbUpdateAgent`

The current task router runs through service-backed LangGraph workflow wrappers
and delegates generation/execution to deterministic Python services. The
handoff is also recorded in each generated JSON tracking file.

## Generated Artifact Layout

Generated automation artifacts now use this layout:

```text
generated/
  project_1/
    brd_v1/
      test_project_1_brd_v1.py
      test_project_1_brd_v1.json
      conftest.py
      pytest.ini
```

The exact project and version names are slugged from `system_name` and
`version`. For example, `PROJECT_1` and `v1` become
`generated/project_1/brd_v1/`.

## Generated Pytest Behavior

Generated test files are class-based pytest automation scaffolds.

Each generated test:

- Is linked to a coverage record.
- Preserves `requirement_id`, `coverage_id`, `chunk_ids`, evidence, and expected
  values derived from the evidence text.
- Uses pytest markers for generated, evidence-bound, and requirement traceability.
- Uses fixtures from generated `conftest.py`.
- Logs start and finish for each test.
- Logs scenario execution details.
- Skips/blocks tests when required protocol, simulator, or device configuration
  is missing.
- In explicit mock mode, validates deterministic evidence-derived assertions.

The generated helper currently logs messages such as:

```text
protocol/interface behavior validation executing in mock mode
```

No real MQTT, REST, CAN, Modbus, device, or application interface calls are made
unless the required endpoint/simulator configuration exists.

## Tracking JSON Behavior

Each generated `.json` sidecar stores:

- Schema version.
- Project and document version.
- Coverage run ID and scope hash.
- Generated file path.
- Harness file paths.
- Dependency audit result.
- Retry policy.
- Agent-style workflow handoff.
- Scenario records.
- Run history.

Each scenario stores:

- `requirement_id`
- `source_doc`
- `doc_version`
- `chunk_ids`
- `expected_values`
- `priority`
- `generated_file`
- `test_function`
- `evidence`
- `last_run_status` after execution

When a generated pytest file is executed, the runner updates the sidecar JSON
with `run_1`, `run_2`, and so on. A passing first run is recorded as:

```json
{
  "state": "executed",
  "status": "PASS"
}
```

## Dependency Audit Behavior

The current `DependencyAuditAgent` behavior is intentionally controlled.

The generator records local pytest harness dependencies:

- Python
- pytest
- logging
- generated `pytest.ini`
- generated `conftest.py`

For protocol scenarios, it records required external dependencies such as REST
base URLs, MQTT brokers, Modbus hosts, CAN interfaces, or simulator
configuration. Missing dependencies produce blocked/skipped execution results.
It does not mutate project dependencies for protocol clients such as MQTT.
Those must be proposed and approved before real interface tests are generated.

## Execution And Retry Behavior

The runner performs this cycle:

1. Generate or reuse artifacts.
2. Validate Python syntax with `py_compile`.
3. Execute pytest from the generated artifact folder.
4. Parse pass, fail, and skip counts.
5. Classify dependency and service blockers.
6. Update SQLite execution records.
7. Update the sidecar JSON run ledger.
8. Retry up to 5 times only for fixable generated-code failures.

Dependency or environment blockers such as missing modules, refused
connections, or timeouts are recorded as blockers. They are not treated as code
generation problems that should be rewritten repeatedly.

## Current CLI/API Surface

The existing commands continue to be the main user surface:

```powershell
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 5
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 5
uv run multi-agentic-rag last-results --system PROJECT_1 --version v1
```

The natural-language task router can also route requests for testcase
generation, execution, and last result lookup.

## Current Storage Behavior

SQLite stores generated test file records and execution result records. When
Neo4j is configured, generated test assets, coverage links, and run results are
also mirrored into the graph as traceability nodes.

The generated test file record now includes:

- Python test file path
- JSON tracking file path
- Harness file paths
- Linked coverage IDs

Detailed scenario tracking currently lives in the generated JSON sidecar. A
future database trace table can adopt that JSON contract and then the sidecar can
become optional after successful DB persistence.

## Current Limits

The implementation does not yet use an LLM to select scenarios or debug failed
tests.

The implementation does not yet create real MQTT, REST, CAN, Modbus, or device
clients.

The implementation does not yet perform real application validation. It blocks
missing external protocol/device dependencies by default and only produces
passing protocol tests in explicit mock mode.

The implementation has service-backed LangGraph wrappers for task routing. The
test-generation internals are still deterministic Python services rather than a
fully decomposed LangGraph subgraph for each generation step.

The generated tests are intentionally ignored from normal project pytest
discovery. They are executed explicitly by the MARAG runner.
