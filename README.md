# Multi-Agentic RAG

LangGraph-orchestrated GraphRAG framework for ingesting versioned requirements documents into PostgreSQL, ChromaDB, and Neo4j, then generating evidence-grounded enterprise user stories from the ingested knowledge base.

Supported agent capabilities:

- `KnowledgeBaseIngestionAgent`: ingests BRD, SRS, PDF, DOCX, TXT, Markdown, and supported document formats into synchronized PostgreSQL, ChromaDB, and Neo4j knowledge representations.
- `UserStoryGenerationAgent`: retrieves independently from PostgreSQL lexical search, ChromaDB semantic search, and Neo4j graph traversal, then produces validated YAML user-story artifacts.

CLI examples:

```powershell
uv run multi-agentic-rag ingest <document-path> --system <system> --version <version> --kb <kb>
```

```powershell
uv run multi-agentic-rag user-stories --system <system> --version <version> --kb <kb>
```

Reasoning-provider selection is configured through `base_config.json` under `reasoning.provider`; `--model` remains only as a temporary compatibility override.
