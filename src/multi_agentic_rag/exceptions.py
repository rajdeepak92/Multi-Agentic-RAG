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


class UserStoryGenerationError(MultiAgenticRagError):
    """Base error for enterprise user-story generation failures."""


class StructuredGenerationError(UserStoryGenerationError):
    """Provider output did not satisfy the required schema."""


class GenerationTokenLimitError(UserStoryGenerationError):
    """Provider output was truncated or exceeded the supported output budget."""


class UserStoryQualityError(UserStoryGenerationError):
    """Generated stories failed mandatory enterprise quality gates."""


class EvidenceInsufficiencyError(UserStoryGenerationError):
    """Available evidence cannot support grounded generation."""


class ProviderCapabilityError(MultiAgenticRagError):
    """Configured deployment does not support a required capability."""


class RetrievalQualityError(MultiAgenticRagError):
    """Retrieved evidence failed mandatory runtime quality gates."""


class FactQualityError(MultiAgenticRagError):
    """Extracted facts failed authoritative fact-quality gates."""
