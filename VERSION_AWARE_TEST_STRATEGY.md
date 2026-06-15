# Version-Aware Test Strategy

## Goal

MARAG must evolve tests across document versions without blindly regenerating or
rerunning everything.

Rule:

```text
No version -> no truth.
No delta -> no impact claim.
No requirement link -> no coverage claim.
```

## Ingestion Lifecycle

When v1 is ingested:

- v1 becomes active unless a newer active version already exists.
- facts, chunks, coverage, generated tests, and results are linked to v1.
- generated files are stored under `generated/<system>/brd_v1/`.

When v2 is ingested:

- v2 becomes active when it is newer.
- previous active versions become superseded.
- historical rows remain queryable.
- old facts are compared with new facts.
- deltas classify changes as added, modified, removed, or unchanged by
  semantic key.

## Fact Identity

Each fact stores:

- `fact_id`
- `fact_key`
- `semantic_key`
- `document_id`
- `version`
- `chunk_id`
- `requirement_id`

Current semantic identity defaults to deterministic `fact_key`. Future domain
packs can replace or enrich this with ontology-aware keys.

## Coverage Impact

Coverage records store:

- `fact_id`
- `semantic_key`
- `impact_status`
- `lifecycle_status`
- `previous_coverage_id`
- `superseded_by`

Impact statuses:

- `unchanged`
- `needs_data_update`
- `needs_code_update`
- `needs_regeneration`
- `new_required`
- `superseded`

Current implementation maps added facts to `new_required`, modified facts to
`needs_data_update`, and unchanged facts to prior coverage where a semantic key
match exists.

## Test Reuse Rules

Unchanged fact:

- reuse previous coverage mapping.
- generate traceability for the new version.
- skip unchanged scenario during execution unless forced.

Modified fact:

- update test data/assertions.
- rerun affected scenario.

Added fact:

- generate a new scenario/test.

Removed fact:

- mark old coverage/test records as superseded.
- do not delete old artifacts.

## Selective Execution

Default execution:

- execute changed/new scenarios.
- skip unchanged already-covered scenarios.
- block protocol/device scenarios when dependencies are missing.

Force execution:

- `run-testcases --force-run-all` rewrites generated scenario data with
  `force_run_all=true`.
- unchanged scenarios execute instead of being skipped.

## Sidecar And DB Updates

The sidecar v3 stores:

- selected scenarios.
- facts used.
- changed and unchanged facts.
- reused and updated coverage.
- version impact.
- dependency audit.
- run history.
- XML/report paths.

SQLite remains the source of truth for documents, facts, deltas, coverage,
generated files, and execution results. Neo4j mirrors traceability when
available.
