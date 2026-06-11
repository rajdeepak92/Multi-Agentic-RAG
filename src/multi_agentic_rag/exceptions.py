"""Domain exceptions for multi-agentic-rag."""


class MultiAgenticRagError(Exception):
    """Base exception for package-specific errors."""


class ConfigurationError(MultiAgenticRagError):
    """Raised when local configuration is invalid."""


class RegistryError(MultiAgenticRagError):
    """Raised when metadata registry operations fail."""


class IngestionError(MultiAgenticRagError):
    """Raised when document ingestion cannot complete."""


class RetrievalError(MultiAgenticRagError):
    """Raised when retrieval cannot complete."""


class EvidenceError(MultiAgenticRagError):
    """Raised when an answer would violate evidence requirements."""
