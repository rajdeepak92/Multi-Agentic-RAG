# MARAG Test Automation Strategy

## Current Execution Foundation

MARAG is pytest-first.

Generated artifacts live under:

```text
generated/<system>/<brd_version>/
  pytest.ini
  conftest.py
  test_<system>_<version>.py
  test_<system>_<version>.robot
  test_<system>_<version>.json
  reports/
    coverage.json
    run_<timestamp>.xml
```

Robot Framework wrapper files are generated with the pytest and JSON sidecar
artifact set. Robot execution remains future work; pytest is still the
authoritative executable path.

## Pytest Design

Generated pytest files:

- use class-based tests.
- include a generated `ThreePTest.define_test()` method with `results: List[bool]`.
- use `automation_context` from generated `conftest.py`.
- use requirement markers.
- validate evidence, chunk IDs, and expected values.
- skip unchanged version-impact scenarios unless forced.
- call simulator validation in simulator mode.
- call safe REST real-adapter validation in explicit real REST mode.
- never fake protocol/device calls.
- in explicit mock mode, create generated mock device context, warn that no
  actual connection was established, and return deterministic PASS only for the
  mock-labelled flow.

## Dependency Audit

The generator audits:

- execution mode.
- generated harness files.
- external dependencies.
- missing REST/MQTT/Modbus/CAN dependencies.
- simulator readiness.

Execution modes:

- `document_contract`
- `mock`
- `simulator`
- `real`
- `blocked`

Missing dependencies produce skip/block behavior, not fake pass behavior.

Explicit mock execution can be requested with:

```powershell
uv run multi-agentic-rag generate-tests --system PROJECT_1 --version v1 --count 10 --mock
uv run multi-agentic-rag run-testcases --system PROJECT_1 --version v1 --count 10 --mock
```

## Failure Classification

The runner classifies results as:

- `passed`
- `failed`
- `skipped`
- `blocked`

Failure categories:

- `GENERATION_ERROR`
- `ASSERTION_FAILURE`
- `PROTOCOL_UNAVAILABLE`
- `DEPENDENCY_MISSING`
- `ENVIRONMENT_ERROR`

Pytest runs also produce JUnit XML reports.

## JSON Sidecar V4

The sidecar stores:

- project/system/version metadata.
- generated pytest path.
- generated Robot path.
- generated XML path after execution.
- coverage report path.
- mock mode and mock warning.
- protocol adapter metadata.
- simulator/device config metadata.
- Robot keyword mapping metadata.
- LangGraph handoff summaries.
- selected scenarios.
- requirements.
- facts used.
- changed and unchanged facts.
- evidence references.
- dependency audit.
- version impact.
- coverage reuse/update lists.
- run history.
- DB update status.

## Robot Framework Position

Robot generation is active, but Robot execution remains future work:

- current mode emits an orchestration wrapper beside the pytest file.
- Robot execution remains future work.
- pytest remains the authoritative executable path today.

## Adapter Position

Active now:

- local simulator readiness checks for REST/MQTT.
- simulator validation hook in generated pytest.
- safe REST GET validation for explicit real REST mode.

Future:

- REST contract-aware client.
- MQTT broker/topic adapter.
- Modbus simulator/client adapter.
- CAN frame/signal adapter.
- Robot keyword libraries mapped to the same adapter contracts.
