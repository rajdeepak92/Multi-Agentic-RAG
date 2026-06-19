# Architecture

`KnowledgeBaseStoringAgent` is the only ingestion entry point. It coordinates small typed sub-agents for settings, runtime directories, document lineage, parsing, chunking, manifests, fact extraction, deltas, persistence, vector indexing, graph projection, BM25 readiness, and final validation.

## Storage

- PostgreSQL stores systems, documents, document versions, chunks, facts, requirements, entities, deltas, ingestion runs, and retrieval metadata.
- ChromaDB stores retrievable chunk vectors and version/status metadata.
- Neo4j stores the GraphRAG projection for graph traversal and lineage.

## Package Layout

- `agents/`: orchestration and sub-agent wrappers.
- `domain/`: typed DTOs and records.
- `ingestion/`: parsing, version guards, chunking, and manifests.
- `extraction/`: deterministic fact extraction.
- `delta/`: deterministic fact delta analysis.
- `infrastructure/`: PostgreSQL, Chroma, Neo4j, and embedding adapters.
- `retrieval/`: BM25, vector, graph, hybrid fusion, and reranking.
- `config/`: settings, logging, and runtime paths.
