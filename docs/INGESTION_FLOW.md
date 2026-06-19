# Ingestion Flow

`KnowledgeBaseStoringAgent.ingest(document_input, previous_knowledge_base, *, system, version)` runs this sequence:

1. Load settings.
2. Configure structured logging and correlation ID.
3. Ensure runtime directories.
4. Resolve the document path.
5. Validate that filename version hints match `--version`.
6. Hash the source with SHA-256.
7. Infer document metadata such as SRS/BRD type.
8. Copy the managed source into runtime storage.
9. Create a started ingestion run in PostgreSQL.
10. Parse PDF, DOCX, TXT, or Markdown.
11. Chunk pages with deterministic overlap.
12. Write a JSONL chunk manifest.
13. Extract deterministic facts.
14. Load the active previous document version for the system and knowledge base.
15. Load previous facts when the new version supersedes the active version.
16. Compute `added`, `removed`, `modified`, and `unchanged` deltas.
17. Persist document, version, chunks, facts, requirements, entities, deltas, and retrieval metadata in one PostgreSQL transaction.
18. Supersede older active versions when applicable.
19. Upsert active and superseded chunk metadata in Chroma.
20. Check Neo4j readiness.
21. Project the graph with idempotent `MERGE` queries.
22. Confirm PostgreSQL BM25/FTS readiness.
23. Validate counts and statuses.
24. Mark the ingestion run `succeeded`, or mark it `failed` if a run row exists.

When `GRAPHRAG_REQUIRED=true`, Neo4j connection or projection failures fail ingestion after the failure state is recorded when possible.
