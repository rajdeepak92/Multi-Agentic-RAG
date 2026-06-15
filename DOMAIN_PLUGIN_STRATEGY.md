# Domain Plugin Strategy

## Goal

Domain plugins let MARAG scale beyond generic BRD extraction into useful QA
automation for industrial and software systems.

Plugins should define:

- ontology terms.
- extraction hints.
- semantic key rules.
- scenario templates.
- dependency requirements.
- simulator adapters.
- real protocol adapters.
- pytest fixtures.
- optional Robot keywords.

## Domain Packs

Domain packs should be YAML or JSON files stored under a future `domain_packs/`
directory.

Example fields:

- `domain_name`
- `protocols`
- `entities`
- `fact_patterns`
- `semantic_key_rules`
- `scenario_templates`
- `dependency_checks`
- `simulator_adapter`
- `real_adapter`
- `robot_keywords`

## Protocol Roadmap

REST:

- current: endpoint extraction and safe GET real validation.
- next: OpenAPI-aware parser and simulator.

MQTT:

- current: topic extraction and simulator readiness flag.
- next: broker simulator, publish/subscribe validation, payload schema checks.

Modbus:

- current: register/coil extraction.
- next: PyModbus simulator, register boundary checks, polling tests.

CAN:

- current: CAN ID extraction.
- next: frame/signal simulator and timing validation.

## Simulator Readiness

Target GraphRAG mode requires REST/MQTT simulator readiness. Modbus and CAN
remain future adapter work and must block rather than pass when real execution
is requested.

## Unit And Threshold Normalization

Current threshold facts store unit strings. Future domain packs should add:

- unit normalization.
- comparable numeric values.
- boundary semantics.
- min/max/critical labels.
- sensor ontology alignment.

## Extension Contract

Each plugin should expose:

- `detect_domain(chunks, facts)`.
- `normalize_facts(facts)`.
- `plan_scenarios(facts, deltas, coverage)`.
- `audit_dependencies(settings)`.
- `render_pytest(scenario)`.
- `render_robot_keyword(scenario)`.
- `validate_simulator(scenario)`.
- `validate_real_target(scenario)`.

All plugin output must preserve evidence references.
