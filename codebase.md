# Codebase Map

## Composition Root

- `src/multi_agentic_rag/app.py` builds `GraphRagApplication`.
- Public business agents remain `KnowledgeBaseIngestionAgent` and `UserStoryGenerationAgent`.
- `AgentRetrieveAnswer` delegates to `agents/ask/graph.py` for ask behavior.

## Runtime

- `runtime/project.py` resolves project roots from explicit root/config, `PROJECT_ROOT`, `BASE_CONFIG_PATH`, repo markers, then installed package fallback.
- `runtime/config_loader.py` projects `base_config.json` into environment defaults and rejects project paths outside `PROJECT_ROOT`.
- `runtime/device.py` centralizes `cpu` / `cuda` / `auto` selection.
- `config/settings.py` contains environment-backed settings and CPU-safe defaults.

## Ingestion

- `agents/ingestion/graph.py` is the compiled LangGraph path.
- Flow: validate, dependencies, lineage, parse, chunk, segment, facts, requirement discovery, validation, deltas, PostgreSQL, Chroma, Neo4j, finalize.
- `extraction/segments.py` builds source segments.
- `extraction/requirements.py` emits one `RequirementDiscoveryResult`.
- `extraction/semantic_candidates.py` validates strict LLM-proposed candidates.
- `extraction/coverage.py` builds document coverage inventory.
- `extraction/conflicts.py` preserves unresolved conflicting claims.

## Storage

- `infrastructure/postgres/models.py` defines SQLAlchemy tables.
- `infrastructure/postgres/repository.py` is the authoritative repository.
- Normal ingestion persists the supplied `RequirementDiscoveryResult`; rediscovery is reserved for `requirements-rebuild`.
- `infrastructure/chroma/repository.py` stores source chunks and canonical requirements as separate vector records.
- `infrastructure/neo4j/repository.py` projects document versions, chunks, segments, candidates, requirements, evidence, conflicts, artifacts, user stories, retrieval runs, and evidence packs.

## Identity

- `identity.py` is the canonical deterministic hash and ID module.
- `utils/hashing.py` re-exports identity helpers for compatibility.

## Retrieval And Ask

- `retrieval/lexical.py` selects `postgres_fts` by default or explicit `pg_textsearch`.
- `retrieval/hybrid.py` fuses lexical, vector, and graph evidence by provenance.
- Exhaustive requirement queries enumerate active PostgreSQL ledger rows before answering.

## User Stories

- `agents/user_stories/graph.py` enumerates the ledger first, retrieves evidence, fuses candidates, generates stories, records coverage, and writes debug traces.
- `agents/artifacts.py` writes YAML, debug JSON, and trace manifest JSON.

## Config Reference

- `lexical.backend`: `postgres_fts` or `pg_textsearch`.
- `embeddings.model`: default `sentence-transformers/all-MiniLM-L6-v2`.
- `embeddings.dimension`: default `384`.
- `embeddings.device`, `reranking.device`, `reasoning.hf_device`: `cpu`, `cuda`, or `auto`.
- `chroma.collection`: use a versioned collection when embedding fingerprints change.
- `secrets.*_env`: names of environment variables that hold secret values.

## Change Recipes

- Change embedding model: update `base_config.json`, use a new Chroma collection, then reingest or run `chroma-reindex`.
- Enable BM25: set `lexical.backend` to `pg_textsearch`, run Alembic, then `db-check`.
- Add a requirement extractor: emit candidates or requirements through `RequirementDiscoveryResult`; do not rediscover in PostgreSQL persistence.
- Add review output: emit `ReviewEventRecord` and render through the CLI review table.

## Failure Recovery

- PostgreSQL lexical failure: run `db-check` and distinguish DSN, extension support, index presence, and Alembic revision.
- Chroma fingerprint failure: switch to a matching collection or reindex intentionally.
- Neo4j failure: run `graph-check`, verify URI, username, password, and database.
- HF local failure: run `hf-check`; use `HF_REASON_DEVICE=cpu` on CPU-only machines.

## Diagrams

- Root workflow diagram: `work-flow.mermaid`.
