# MARAG Test Generation Strategy

## 1. Purpose

MARAG test generation converts requirement-linked evidence into generated QA
automation assets. Pytest is the current execution foundation. Robot Framework
and reusable keyword mappings are future layers.

Current state:

- Generated tests are placeholder-based.
- Generated tests validate traceability fields.
- The runner validates syntax and executes pytest.
- Results are written to JSON sidecar and SQLite.

Target state:

- Generated tests use dependency audit.
- Tests execute deterministic mocks or simulators when available.
- Missing real dependencies are SKIP or BLOCKED.
- Every scenario and test links to requirement evidence.

## 2. Generated Folder Structure

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

- Generated assets are runtime outputs.
- Do not hard-delete generated assets.
- Do not destructively overwrite without a force path or stale-artifact check.
- Keep generated folders out of normal project pytest discovery.
- Execute generated tests through MARAG commands.

## 3. Pytest Design Rules

Generated `.py` files must:

- Use pytest.
- Use `TestClass` structure.
- Use generated fixtures from `conftest.py`.
- Use `pytest.ini` markers and addopts.
- Use clear logging.
- Be deterministic.
- Be valid Python.
- Pass `py_compile` before pytest execution.
- Link every test to requirement evidence.
- Avoid fake protocol or device calls.

Generated test behavior:

- If a mock or simulator exists, assert against the mock/simulator output.
- If real endpoint configuration exists, run against the real endpoint only when
  explicitly configured.
- If required dependency is absent, mark SKIP or BLOCKED.
- If generated code is invalid, classify as GENERATION_ERROR.
- If assertion fails, classify as ASSERTION_FAILURE.

## 4. Fixture And Harness Strategy

`pytest.ini` should define:

- Strict marker behavior.
- Generated-test markers.
- Requirement markers.
- Logging options.
- Default addopts.

`conftest.py` should define:

- `automation_context`.
- Generated-test logging hooks.
- Optional fixture factories for mocks, simulators, and protocol clients.
- Skip/block helpers for unavailable external dependencies.

Harness rules:

- Existing user code should not be overwritten destructively.
- Harness files should be regenerated only when MARAG owns the generated folder
  or when force/stale-artifact logic allows it.
- Real protocol fixtures must fail closed: absent config means SKIP/BLOCKED.

## 5. Dependency Audit Strategy

`DependencyAuditAgent` should check:

- Generated folder exists.
- `pytest.ini` exists and is valid.
- `conftest.py` exists and is valid.
- Required fixtures exist.
- Required Python packages are importable.
- Required protocol adapter config exists.
- Required simulator or mock config exists.
- Required real endpoints are configured when real execution is requested.

Dependency statuses:

| Status | Meaning |
| --- | --- |
| ready | All dependencies for selected execution mode are available |
| partial | Some optional dependencies are missing but tests can run with mocks/skips |
| blocked | Required dependency is missing |
| skipped | Test intentionally not applicable in current mode |

## 6. Scenario Selection Strategy

`ScenarioSelectionAgent` should rank scenarios using:

- Requirement criticality.
- Safety impact.
- Negative behavior.
- Boundary behavior.
- Protocol importance.
- Sensor threshold importance.
- Coverage gaps.
- Evidence confidence.
- Graph path availability.
- Execution feasibility.

No scenario should claim coverage unless it links to requirement evidence.

## 7. JSON Sidecar Contract

Minimum proposed schema:

```json
{
  "schema_version": "test-automation-tracking.v2",
  "project": "",
  "document_id": "",
  "document_version": "",
  "source_document_path": "",
  "generated_test_file": "",
  "scenario_group": "",
  "selected_scenarios": [],
  "requirements": [],
  "extracted_facts_used": [],
  "evidence_refs": [],
  "domain": "",
  "protocols": [],
  "dependency_audit": {
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

Recommended scenario fields inside `selected_scenarios`:

- `scenario_id`
- `scenario_name`
- `requirement_id`
- `document_id`
- `document_version`
- `chunk_ids`
- `fact_ids`
- `evidence_refs`
- `expected_values`
- `domain`
- `protocols`
- `execution_mode`
- `dependency_status`
- `last_run_status`

## 8. Failure Classification

| Classification | Use when |
| --- | --- |
| PASS | Test executed successfully against selected target |
| FAIL | Test executed and failed |
| SKIP | Test intentionally skipped by condition |
| BLOCKED | Test could not run because a dependency or endpoint is missing |
| GENERATION_ERROR | Generated code, config, or sidecar is invalid |
| ENVIRONMENT_ERROR | Python, pytest, filesystem, or runtime environment failed |
| ASSERTION_FAILURE | Test ran and assertion failed |
| PROTOCOL_UNAVAILABLE | MQTT broker, Modbus endpoint, CAN interface, REST service, simulator, or device is unavailable |

Rules:

```text
No fake protocol calls.
No real dependency -> SKIP/BLOCKED, not PASS.
No evidence -> no generated scenario.
No requirement link -> no coverage claim.
```

## 9. Future Robot Framework Mapping

Robot Framework should be added after pytest mock/simulator execution is stable.

Future mapping:

- Requirement-linked scenario -> Robot test case.
- Domain adapter operation -> reusable keyword.
- Pytest fixture concept -> Robot resource or library setup.
- JSON sidecar -> shared traceability ledger.
- Simulator/mock config -> Robot variable or resource file.

Robot generation should not be enabled by default until:

- Keyword mappings exist.
- Domain adapters define reusable operations.
- Sidecar schema can track Robot outputs.
- Execution classification supports Robot result statuses.

## 10. Acceptance Criteria

- Generated tests compile with `py_compile`.
- Generated pytest executes from the artifact folder.
- JSON sidecar validates before DB update.
- Every generated scenario has requirement and evidence references.
- Missing dependencies produce SKIP or BLOCKED.
- Result status is written to JSON and SQLite.
- Current local workflow remains usable without Docker, PostgreSQL,
  OpenSearch, MinIO/S3, managed embeddings, or paid APIs.
