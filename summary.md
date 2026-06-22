# Multi-Agentic RAG Summary

## Project Intent

Multi-Agentic RAG is a strict enterprise GraphRAG runtime for versioned engineering documents. It turns BRDs, SRS files, requirements, and design documents into traceable knowledge across PostgreSQL, ChromaDB, and Neo4j, then uses that evidence for retrieval, grounded answers, generated user stories, and LangGraph-orchestrated workflows.

The current runtime is intentionally narrow and auditable:

- PostgreSQL is mandatory.
- ChromaDB is mandatory.
- Neo4j is mandatory.
- `KnowledgeBaseStoringAgent` is the canonical ingestion path.
- OpenAI reasoning is the default.
- Hugging Face reasoning is opt-in with `--model hf`.
- BGE-M3 sentence-transformer embeddings are the semantic default.
- App-owned caches, model downloads, Chroma persistence, and runtime files default to `.global_cache/`.
- Root `base_config.json` is the single app-owned non-secret runtime profile.
- `.env` is only for secret values referenced by name from `base_config.json`.
- No SQLite, FastAPI, MCP, UI, or workspace layer is part of the current authoritative workflow.
- QA command aliases (`qa-ingest`, `qa-user-stories`, `qa-doctor`) run from the repository root and add run folders, redacted logs, CUDA planning, and compatibility wrappers without changing `multi_agentic_rag` imports.

## Exact Architecture

```text
Typer CLI
  -> KnowledgeBaseStoringAgent
      -> SettingsBootstrapAgent
      -> RuntimeDirectoryAgent
      -> DocumentResolutionAgent
      -> DocumentVersioningAgent
      -> HashingAgent
      -> SourceStorageAgent
      -> ParserAgent
      -> ChunkingAgent
      -> ManifestAgent
      -> FactExtractionAgent
      -> FactEnrichmentAgent
      -> DeltaAnalysisAgent
      -> PostgresPersistenceAgent
      -> ChromaIndexingAgent
      -> Neo4jGraphAgent
      -> ValidationAgent

Typer CLI
  -> HybridKnowledgeRetriever
      -> BM25Retriever
      -> VectorRetriever
      -> GraphRetriever
      -> optional sentence-transformers reranker

Typer CLI
  -> AgentRetrieveAnswer
  -> AgentUserStoryBuilder
  -> LangGraphWorkflowRunner
      -> IntentRouterAgent
      -> missing-slot check
      -> WorkflowPlannerAgent
      -> agent dispatch
      -> FlowValidatorAgent
      -> final response
```

Primary modules:

| Area | Path |
| --- | --- |
| CLI | `src/multi_agentic_rag/cli.py` |
| Ingestion orchestrator | `src/multi_agentic_rag/agents/knowledge_base.py` |
| Ingestion sub-agents | `src/multi_agentic_rag/agents/sub_agents.py` |
| High-level agents | `src/multi_agentic_rag/agents/high_level.py` |
| LangGraph workflow | `src/multi_agentic_rag/agents/workflow.py` |
| Artifact writer | `src/multi_agentic_rag/agents/artifacts.py` |
| Domain models | `src/multi_agentic_rag/domain/models.py` |
| Settings | `src/multi_agentic_rag/config/settings.py` |
| PostgreSQL repository | `src/multi_agentic_rag/infrastructure/postgres/repository.py` |
| Chroma repository | `src/multi_agentic_rag/infrastructure/chroma/repository.py` |
| Neo4j repository | `src/multi_agentic_rag/infrastructure/neo4j/repository.py` |
| Embeddings | `src/multi_agentic_rag/infrastructure/embeddings/provider.py` |
| Retrieval | `src/multi_agentic_rag/retrieval/` |
| Reasoning clients | `src/multi_agentic_rag/llm/` |
| Parsing and chunking | `src/multi_agentic_rag/ingestion/` |
| Extraction | `src/multi_agentic_rag/extraction/` |
| Deltas | `src/multi_agentic_rag/delta/` |
| Migrations | `migrations/versions/` |

## What Each Tool Does

| Command | Purpose |
| --- | --- |
| `ingest` | Ingest one PDF, DOCX, TXT, Markdown, or Markdown-like document version into PostgreSQL, ChromaDB, and Neo4j. |
| `ingest-directory` | Ingest every supported document in a directory, recursively by default. |
| `retrieve` | Return ranked evidence chunks from BM25, vector, and graph retrieval. |
| `ask` | Retrieve and validate evidence, then synthesize an answer with OpenAI or Hugging Face. |
| `user-stories` | Generate user-story YAML and debug JSON from an already ingested version. |
| `ingest-and-user-stories` | Compose one ingest followed by user-story generation. |
| `run` | Route a natural-language task through LangGraph. |
| `db-check` | Check PostgreSQL and configured lexical-search readiness. |
| `chroma-check` | Check Chroma collection readiness. |
| `graph-check` | Check Neo4j read/write/delete behavior with a temporary node. |
| `health-check` | Check PostgreSQL, ChromaDB, and Neo4j together. |
| `clean-system-state` | Clear PostgreSQL rows, Chroma vectors, and Neo4j nodes together, with optional runtime/cache deletion for `--all`. |
| `clean-postgres-state` | Clear only PostgreSQL GraphRAG rows through `PostgresKnowledgeRepository.clear`. |
| `clean-chroma-state` | Clear only Chroma vectors through `ChromaVectorRepository.clear`. |
| `clean-neo4j-state` | Clear only Neo4j nodes through `Neo4jGraphRepository.clear`. |

## Why Each Backend Exists

PostgreSQL is the authoritative store. It keeps source document lineage, versions, chunks, facts, requirements, entities, deltas, ingestion runs, canonical facts, retrieval metadata, workflow runs, workflow steps, and generated artifact audit records. It also owns lexical search.

`pg_textsearch` creates a PostgreSQL BM25 index over stored chunk text. With `BM25_BACKEND=pg_textsearch`, readiness checks require the `pg_textsearch` extension and `idx_chunks_text_bm25`. Lexical retrieval uses that index and marks results with source `bm25`. `BM25_BACKEND=postgres_fts` is the explicit native FTS fallback and marks results with source `fts`.

ChromaDB stores semantic vectors for chunks. It is used by `VectorRetriever` for query similarity. It is not the source of truth for document metadata; metadata is copied into Chroma so vector filters can stay scoped by system, knowledge base, version, and active/superseded status.

Neo4j stores the graph projection. It supports graph expansion from facts, requirements, entities, document versions, chunks, passages, sentences, deltas, user stories, and artifacts. It exists for lineage and traversal that would be awkward or expensive as pure row queries.

`.global_cache/` is the project-local boundary for app-owned cache state. It contains runtime documents/manifests, Chroma persistence, model caches, and placeholders for db/graph app cache folders. PostgreSQL and Neo4j server data directories remain controlled by those services.

OpenAI provides the default structured reasoning path for intent routing, workflow planning, answer synthesis, story generation, validation, and optional ingest-side fact review.

Hugging Face provides a local opt-in structured reasoning path with `--model hf`. It uses the same high-level contracts and Pydantic validation, but model quality and local resource needs are operator responsibilities.

## Current Data Flow

Ingestion:

```text
source file
-> resolve absolute path
-> validate version hint
-> hash file
-> copy to .global_cache/runtime/documents
-> parse pages or logical text units
-> chunk text
-> write manifest JSONL
-> extract deterministic facts
-> optionally enrich ambiguous facts with OpenAI or HF metadata
-> load prior active version
-> compute deltas when superseding
-> persist PostgreSQL rows in one transaction
-> index chunks in ChromaDB
-> refresh superseded Chroma metadata when needed
-> project Neo4j graph
-> re-check PostgreSQL BM25/FTS readiness
-> mark ingestion run succeeded
```

Retrieval:

```text
query
-> PostgreSQL BM25 or FTS search
-> Chroma vector search
-> Neo4j graph expansion and chunk hydration
-> reciprocal-rank fusion
-> graph overlap boost
-> optional cross-encoder rerank
-> evidence ranking and trace validation
```

User-story generation:

```text
system + kb + version
-> hybrid retrieval with a user-story query
-> evidence validation
-> structured story generation
-> story validation
-> YAML output
-> debug JSON output
-> PostgreSQL artifact record
-> Neo4j UserStory and Artifact lineage
```

Natural-language workflow:

```text
task text
-> reasoning-backed intent routing
-> missing-slot check
-> reasoning-backed workflow plan
-> high-level agent dispatch
-> flow validation
-> PostgreSQL workflow audit
-> final response
```

## Strict Contracts

- Ingestion must use PostgreSQL, ChromaDB, and Neo4j.
- Ingestion fails if PostgreSQL BM25/FTS readiness is missing.
- Ingestion fails if Chroma is unavailable or indexes fewer chunks than produced.
- Ingestion fails if Neo4j is unavailable.
- Ingestion fails if no chunks are created.
- Ingestion fails if no facts are extracted.
- Ingestion fails if extracted facts point to missing chunks.
- `ask` validates retrieved evidence before calling a reasoning backend.
- `ask` refuses when evidence is empty or untraceable.
- `user-stories` requires traceable evidence for the requested version.
- Generated artifacts must include source chunk traceability.
- Cleanup must use repository `clear` methods rather than parallel deletion logic.
- Individual cleanup commands require either `--system` or `--all`, reject `--all` with `--system`, reject `--kb` with `--all`, and prompt unless `--yes` is supplied.
- App-owned cache paths must remain inside `PROJECT_ROOT`; first command execution creates `.global_cache/` and configured subdirectories.
- OpenAI remains the default reasoning backend.
- Hugging Face is opt-in through `--model hf`.
- `hash` embeddings are a deterministic fallback for tests, not a semantic production default.

## Rebuild This Exact Project Prompt

Use this prompt to recreate the current project shape from scratch:

```text
Build a Python 3.12 package named multi-agentic-rag with a Typer CLI entry point named multi-agentic-rag and alias multi-rag. The runtime must be a strict GraphRAG platform for versioned enterprise documents.

Implement a canonical KnowledgeBaseStoringAgent that ingests PDF, DOCX, TXT, Markdown, and .markdown files. Its sequence must be: load settings, create project-local `.global_cache` and runtime directories, resolve source path, validate requested version against filename hints, hash the source, copy the managed source into `.global_cache/runtime/documents`, parse the document, chunk parsed pages, write a JSONL manifest, extract deterministic facts, optionally enrich ambiguous facts with a structured reasoning client, load the previous active version, compute fact deltas when superseding, persist authoritative rows in PostgreSQL, index every chunk in ChromaDB, refresh superseded chunk metadata, project Neo4j graph nodes and relationships, re-check lexical readiness, and mark ingestion runs succeeded or failed.

Use PostgreSQL as the authoritative system of record through SQLAlchemy async and Alembic. Store systems, documents, document_versions, chunks, facts, requirements, entities, deltas, ingestion_runs, retrieval_metadata, canonical_facts, workflow_runs, workflow_steps, and artifact_records. Support BM25_BACKEND=pg_textsearch as the default lexical backend using the pg_textsearch extension and idx_chunks_text_bm25 over chunk text. Return retrieval source bm25 for that path. Support BM25_BACKEND=postgres_fts as an explicit fallback using native PostgreSQL full-text search and source fts. Treat legacy BM25_BACKEND=postgres as postgres_fts.

Use ChromaDB as the persistent vector store with `CHROMA_PATH=.global_cache/vectorstore/chroma` by default. Default embeddings must be sentence_transformers with BAAI/bge-m3 and EMBEDDING_DIMENSIONS=1024. Wire HF_TOKEN into sentence-transformers and reranker model loading. Route HF_HOME, TRANSFORMERS_CACHE, SENTENCE_TRANSFORMERS_HOME, TORCH_HOME, and HF_REASON_CACHE_DIR into `.global_cache/models`. Coerce embedding vectors to plain Python floats before Chroma upsert. Keep hash embeddings only as a deterministic fallback.

Use Neo4j 5.x as the mandatory graph projection. Create constraints for System, Document, DocumentVersion, Chunk, Passage, Sentence, Fact, Requirement, Entity, Delta, Artifact, and UserStory identities. Project chunks, passages, sentences, facts, requirements, entities, deltas, document version supersession, and generated user-story artifact lineage. Graph retrieval must expand from entity, fact, requirement, and related requirement paths and hydrate chunk records from PostgreSQL.

Implement retrieval as BM25Retriever, VectorRetriever, GraphRetriever, and HybridKnowledgeRetriever. Run configured retrievers concurrently. Fuse results with reciprocal-rank fusion using k=60, preserve source signals, boost graph overlap modestly, and optionally rerank with a sentence-transformers cross-encoder. Evidence validation must drop empty or untraceable results.

Implement OpenAIReasoningClient as the default structured reasoning backend and HuggingFaceReasoningClient as an opt-in backend selected with --model hf. Share structured Pydantic contracts for intent routing, workflow planning, answer synthesis, user-story generation, user-story validation, and fact review. Do not automatically fall back between OpenAI and Hugging Face.

Implement high-level agents: AgentIngestDocument, AgentRetrieveAnswer, and AgentUserStoryBuilder. AgentRetrieveAnswer must retrieve and validate evidence before model synthesis and refuse with "I could not find this in the selected project documents" when evidence is missing. AgentUserStoryBuilder must retrieve version-scoped evidence, generate required user-story fields, validate generated stories, write YAML under generated/<system>/<kb>/<version>/user_stories/, write debug JSON under generated/<system>/<kb>/<version>/debug/, record PostgreSQL artifact rows, and project Neo4j story/artifact lineage.

Implement LangGraphWorkflowRunner with nodes for intent routing, missing-slot check, workflow planning, agent dispatch, and final response. Audit workflow runs and steps in PostgreSQL. Supported intents must include answer query, ingest document, build user stories, and ingest then build user stories.

Expose Typer commands: ingest, ingest-directory, retrieve, ask, user-stories, ingest-and-user-stories, run, db-check, chroma-check, graph-check, health-check, clean-system-state, clean-postgres-state, clean-chroma-state, and clean-neo4j-state. Keep --model openai as default and --model hf as opt-in on reasoning commands. Cleanup commands must use PostgresKnowledgeRepository.clear, ChromaVectorRepository.clear, and Neo4jGraphRepository.clear. Individual cleanup commands must support --system, optional --kb, --all, and --yes; reject invalid scope combinations; and print Rich tables with Target and Deleted columns.

Write focused unit tests for ingestion validation, repository readiness, BM25 and FTS SQL generation, Chroma filtering, Neo4j graph projection, retrieval fusion, evidence refusal, HF token propagation, workflow agents, and all cleanup command scope/output behavior. Provide README.md, run.md, and summary.md as the authoritative docs. Do not include current FastAPI, MCP, SQLite, UI, or generated QA automation surfaces.
```
