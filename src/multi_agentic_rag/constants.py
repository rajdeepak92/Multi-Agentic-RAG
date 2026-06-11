"""Project-wide constants."""

PACKAGE_NAME = "multi-agentic-rag"
IMPORT_PACKAGE_NAME = "multi_agentic_rag"
CLI_NAME = "multi-agentic-rag"
CLI_ALIAS = "multi-rag"

RUNTIME_DIR_NAME = ".multi_agentic_rag"
DOCUMENTS_DIR_NAME = "documents"
CHROMA_DIR_NAME = "chroma"
EXPORTS_DIR_NAME = "exports"
REGISTRY_DB_NAME = "registry.db"

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 150

GRAPH_COLLECTION_NAME = "multi_agentic_rag_chunks"

SCIENTIFIC_RULES = (
    "No evidence -> no answer.",
    "No version -> no truth.",
    "No delta -> no impact claim.",
    "No requirement link -> no coverage claim.",
)
