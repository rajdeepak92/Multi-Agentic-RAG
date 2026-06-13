# MARAG Execution Flow

## 1. End-To-End Flow

The target execution path starts with a local document path and ends with
generated, executed, and traceable QA automation artifacts.

```text
Local document path
-> document resolution
-> parsing
-> chunking
-> fact extraction
-> metadata, keyword, vector, and graph indexing
-> domain analysis
-> scenario selection
-> dependency audit
-> pytest harness generation
-> pytest test generation
-> JSON sidecar write
-> syntax validation
-> pytest execution
-> failure classification
-> sidecar run_history update
-> SQLite DB update
-> report output
```

## 2. Document Ingestion Lifecycle

Input:

- `source_path`
- `system_name`
- `version`

Required rule:

```text
No document path -> no ingestion.
```

Current behavior:

1. Validate the source path exists.
2. Validate filename version hints against the requested version when present.
3. Copy the source file into `.multi_agentic_rag/documents`.
4. Parse PDF/DOCX content.
5. Extract tables where parser support exists.
6. Chunk content with lineage metadata.
7. Extract deterministic facts.
8. Write document, chunk, and fact records to SQLite.
9. Update SQLite FTS5/BM25 keyword index.
10. Write parsed JSONL artifacts under `.multi_agentic_rag/objects`.
11. Update vector store through Chroma or Weaviate.
12. Update Neo4j graph when configured and reachable.
13. Preserve active/superseded lifecycle state.

Future LangGraph owner:

- `DocumentResolverAgent`
- `IngestionAgent`
- `DomainAnalyzerAgent`
- `DatabaseUpdateAgent`

## 3. Test Generation Lifecycle

Input:

- `system_name`
- `version`
- `scenario_count`
- optional `output_dir`

Required rule:

```text
No requirement link -> no coverage claim.
```

Flow:

1. Resolve the document scope from SQLite.
2. Retrieve requirement-linked evidence.
3. Build or reuse a coverage run.
4. Select scenarios by evidence, requirement criticality, domain importance,
   boundary behavior, and coverage gaps.
5. Audit the generated folder for existing harness files.
6. Audit runtime dependencies and external dependencies.
7. Create or update `pytest.ini`.
8. Create or update `conftest.py`.
9. Generate class-based pytest tests.
10. Write the JSON sidecar.
11. Validate sidecar schema before DB update.
12. Store generated file metadata in SQLite.

Current behavior is placeholder-based. Future behavior should use mocks or
simulators when available and SKIP/BLOCK when required dependencies are absent.

## 4. Generated Folder Lifecycle

Target layout:

```text
generated/
  <project_or_system_name>/
    <document_version_or_doc_id>/
      pytest.ini
      conftest.py
      test_<scenario_group>.py
      test_<scenario_group>.json
```

Example:

```text
generated/
  siimcs/
    brd_v1/
      pytest.ini
      conftest.py
      test_modbus_temperature_polling.py
      test_modbus_temperature_polling.json
```

Rules:

- Do not hard-delete generated assets.
- Do not destructively overwrite user-modified code without a force path or
  stale-artifact check.
- Generated project pytest discovery must stay isolated from normal repository
  tests.
- Generated tests are executed explicitly by MARAG.

## 5. JSON Sidecar Lifecycle

The sidecar is the portable tracking ledger for generated automation.

Write during generation:

- Project and document identifiers.
- Source document path.
- Generated file path.
- Scenario group.
- Selected scenarios.
- Requirements.
- Evidence references.
- Domain and protocols.
- Dependency audit.
- Coverage metadata.
- Initial empty `run_history`.
- DB update status.

Update after execution:

- Add run ID.
- Add timestamp.
- Add command.
- Add status.
- Add failure category and reason.
- Add pass/fail/skip counts if available.
- Add stdout/stderr paths or captured output references.
- Update scenario `last_run_status`.
- Update DB status after SQLite persistence.

Recommended lifecycle:

```text
write sidecar
-> validate sidecar JSON
-> update generated_test_files DB row
-> execute pytest
-> append run_history
-> update test_run_results DB row
-> mark db_update_status
```

## 6. Database Update Lifecycle

Current SQLite records:

- `documents`
- `chunks`
- `facts`
- `deltas`
- `coverage`
- `coverage_runs`
- `generated_test_files`
- `test_run_results`

Target DB update rules:

- DB updates should not claim coverage without requirement evidence.
- Generated file DB rows should reference sidecar path and coverage IDs.
- Execution result DB rows should mirror final sidecar run status.
- DB update status should be reflected in the sidecar.
- PostgreSQL should remain a future compatible backend, not a current
  requirement.

## 7. Execution Lifecycle

Current pytest execution:

1. Generate or reuse pytest artifacts.
2. Run `py_compile` on generated Python.
3. Run pytest from the generated artifact folder.
4. Capture stdout/stderr.
5. Parse passed, failed, and skipped counts.
6. Detect dependency blockers.
7. Store result in SQLite.
8. Append JSON sidecar `run_history`.
9. Retry only for fixable generated-code failures.

Target execution agents:

- `SyntaxValidationAgent`
- `TestExecutionAgent`
- `FailureClassifierAgent`
- `JsonSidecarAgent`
- `DatabaseUpdateAgent`
- `ReportGeneratorAgent`

## 8. Status Model

Top-level execution statuses:

| Status | Meaning |
| --- | --- |
| PASS | Test executed successfully against the configured target |
| FAIL | Test executed and failed |
| SKIP | Test intentionally skipped because configured conditions were not met |
| BLOCKED | Test could not run because a dependency, endpoint, simulator, or environment is missing |

Failure categories:

| Category | Meaning |
| --- | --- |
| GENERATION_ERROR | Generated code or sidecar is invalid |
| ENVIRONMENT_ERROR | Python, pytest, filesystem, or runtime environment problem |
| ASSERTION_FAILURE | Test ran and assertion failed |
| PROTOCOL_UNAVAILABLE | Protocol client, broker, device, simulator, or endpoint unavailable |
| DEPENDENCY_MISSING | Required Python package, fixture, config, or external service missing |
| EVIDENCE_MISSING | Scenario or test lacks required evidence/reference links |

Rules:

```text
No real dependency -> SKIP/BLOCKED, not PASS.
No fake protocol calls.
No unsupported coverage status.
No generated test without evidence refs.
```

## 9. Informative Chatbot Flow

Flow:

```text
user question
-> intent detection
-> document/version/status scope
-> graph retrieval
-> keyword retrieval
-> vector retrieval
-> metadata/fact lookup
-> evidence merge and dedupe
-> evidence verification
-> answer or controlled no-answer
```

Rules:

- No evidence -> no answer.
- No graph path -> no relationship claim.
- No delta -> no impact claim.
- No requirement link -> no coverage claim.
