# Retrieval Architecture

Retrieval returns ranked `RetrievalResult` records with chunk lineage and source labels.

## Components

- `BM25Retriever`: PostgreSQL full-text search over `chunks.text`.
- `VectorRetriever`: Chroma vector similarity search.
- `GraphRetriever`: Neo4j graph expansion to related chunks.
- `HybridKnowledgeRetriever`: reciprocal-rank fusion and chunk de-duplication.
- `RerankingService`: pluggable interface with a no-op default.

The default rank fusion is deterministic: each source contributes `1 / (60 + rank)`, and results sort by fused score then chunk ID.
