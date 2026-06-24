# Enterprise GraphRAG Upgrade Migration, Re-Index, and Rollback Plan

## Recorded Baseline

- Baseline branch: `main`
- Baseline commit: `b934b1e7cd1a9e06c9a537ce9b8000bb541b085a`
- Feature branch: `feature/enterprise-graphrag-quality-upgrade`
- Current Alembic revision: `20260624_0006`
- Current Chroma collection: `multi_agentic_rag_chunks_minilm_l6_v1`
- Current embedding fingerprint: `11e07ff06dcafcdc13104394a9d35fdaaba324dc803dc1b62d67a783e935534c`
- Current embedding space: `sentence_transformers`, `sentence-transformers/all-MiniLM-L6-v2`, revision `default`, dimension `384`, cosine, normalized
- Current Neo4j constraints: 18 uniqueness constraints including `Requirement.requirement_pk`, `Fact.fact_id`, `EvidenceSpan.evidence_id`, `UserStory.story_key`, `Chunk.chunk_id`, `Segment.segment_id`, `RetrievalRun.retrieval_run_id`, and `Artifact.artifact_id`
- Current PostgreSQL counts: `requirements=0`, `facts=0`, `requirement_coverage=0`
- Historical poor-quality run retained: `generated/runs/RUN_20260623_215543_fc1037`
- Historical run quality signature: 52 YAML stories, all using `generation_mode: deterministic_ledger_fallback`
- Baseline tests: `uv run --no-sync pytest -q` -> `158 passed`

## Migration Plan

- Add new schema objects with backward-compatible Alembic migrations; do not drop or rewrite existing requirement, fact, chunk, document, artifact, or trace tables.
- Add nullable columns or new tables for semantic units, fact quality, retrieval metrics, generation attempts, story groups, story quality evaluations, publication decisions, and provider usage.
- Preserve existing Requirement Ledger identity and lifecycle fields. New enrichment tables reference current primary keys instead of replacing them.
- Keep deterministic extraction authoritative. Semantic review records remain candidates until deterministic validation and configured approval permit promotion.
- Use idempotency keys for semantic units, fact quality rows, retrieval benchmark runs, story groups, generation attempts, story artifacts, coverage rows, and publication decisions.
- Treat any downgrade that would discard audit history as non-destructive rollback: disable new features by configuration and retain rows for later inspection.

## Chroma Re-Index Plan

- Create a new collection for the Azure enterprise embedding space. Do not overwrite `multi_agentic_rag_chunks_minilm_l6_v1`.
- Validate the Azure embedding provider with `embedding-check` before indexing.
- Persist the validated returned embedding dimension into the embedding-space fingerprint.
- Re-index semantic units for a system/version into the new collection.
- Validate record counts by semantic unit type, embedding dimension, empty-vector rejection, and fingerprint compatibility.
- Run sample retrieval and the SIIMCS golden retrieval benchmark before activating the new collection.
- Activate the new collection only after quality gates pass.
- Retain the previous collection until rollback risk is accepted.

## Rollback Plan

- If migrations fail before commit, rely on PostgreSQL transactional DDL where supported and rerun `alembic current` to verify the unchanged revision.
- If a new migration is applied but rollout fails, set provider back to the previous non-Azure provider and Chroma collection in `base_config.json`; do not delete newly added audit rows.
- If the Azure collection fails quality gates, keep the old Chroma collection active and do not run `activate-index`.
- If story generation or publication fails, leave the run marked `failed`; do not create coverage rows, story nodes, or published story artifacts.
- If Neo4j projection fails after staged story validation, remove staged artifacts and do not mark publication complete.
- Historical artifacts under `generated/` are evidence and must not be deleted automatically.

## Cutover Gates

- `azure-check` passes for configured deployments and capability cache is fresh.
- `embedding-check` validates dimensions and vector integrity.
- `reranker-check` validates structured output and candidate ID integrity.
- Alembic upgrade succeeds.
- Chroma re-index count and sample query validation pass.
- Fact golden evaluation does not regress.
- Retrieval golden evaluation does not regress beyond configured tolerance.
- User-story quality gates pass with no fallback, no generic prose, full traceability, and mandatory coverage complete.
