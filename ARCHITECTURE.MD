# multi-agentic-rag Architecture

## Project Name

multi-agentic-rag

## Current Phase

Phase 1.1 local-first Option-4 implementation.

## Architecture Style

Knowledge Graph + GraphRAG + Multi-Agent.

## Current Local Components

- Python 3.12
- uv
- FastAPI
- Typer CLI
- SQLite registry
- ChromaDB local vector store
- Neo4j Desktop/local DBMS
- PyMuPDF parser
- LangGraph workflow skeleton
- LangChain helper layer
- MCP placeholder only

## Current Data Flow

Source BRD PDFs enter through the CLI or FastAPI ingestion boundary. The app parses
PDF text with PyMuPDF, copies managed document versions into
`.multi_agentic_rag/documents/`, chunks the extracted text, runs deterministic
extractors, writes document/chunk/fact/delta/coverage metadata to SQLite, upserts
chunks into ChromaDB, writes lineage and evidence nodes to Neo4j, updates the
active/superseded version lifecycle, generates deterministic deltas, and serves
query, delta, and coverage outputs from supported evidence only.

## Version Lifecycle

V1 is active when first ingested. V2 is ingested later and becomes active. V1 is
marked superseded, old evidence remains stored, and no hard delete is performed.
The active document supersedes the prior document with this relationship:
`new active document -[:SUPERSEDES]-> old document`.

## Real BRD Input Files

- `D:\Multi-Agentic-RAG\SIIMCS_BRD_V1.pdf`
- `D:\Multi-Agentic-RAG\SIIMCS_BRD_V2.pdf`

## Scientific Rules

- No evidence -> no answer.
- No version -> no truth.
- No delta -> no impact claim.
- No requirement link -> no coverage claim.

## What Is Built So Far

- Local CLI commands for doctor, graph-check, demo PDF generation, demo workflow,
  exact real BRD validation, and exact real BRD ingestion.
- FastAPI health and doctor endpoints plus current document/query/delta/coverage
  route foundation.
- SQLite registry for documents, chunks, facts, deltas, and coverage drafts.
- ChromaDB local vector indexing with deterministic fallback embeddings.
- Neo4j graph writes for System, Document, Chunk, Fact, Requirement, Entity, and
  Delta nodes with idempotent MERGE queries.
- Deterministic GraphRetriever methods for current facts, historical facts,
  deltas, and lineage.
- Deterministic V1/V2 threshold delta proof for demo PDFs.

## What Is Not Done Yet

- full MCP server
- production UI
- PostgreSQL
- Weaviate
- OpenSearch
- MinIO/S3
- production auth
- advanced semantic delta
- full LLM extraction
- enterprise deployment
