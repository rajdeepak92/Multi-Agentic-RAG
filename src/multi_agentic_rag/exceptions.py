"""Classified domain errors."""

from __future__ import annotations


class MultiAgenticRagError(Exception):
    """Base error for this package."""


class ConfigError(MultiAgenticRagError):
    """Configuration is incomplete or invalid."""


class IngestionError(MultiAgenticRagError):
    """Document ingestion failed."""


class PersistenceError(MultiAgenticRagError):
    """Authoritative storage failed."""


class RetrievalError(MultiAgenticRagError):
    """Retrieval failed."""


class ServiceUnavailableError(MultiAgenticRagError):
    """A required external service is unavailable."""
