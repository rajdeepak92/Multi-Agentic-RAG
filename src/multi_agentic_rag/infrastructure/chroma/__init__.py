"""ChromaDB adapter."""

from multi_agentic_rag.infrastructure.chroma.fingerprint import EmbeddingSpaceFingerprint
from multi_agentic_rag.infrastructure.chroma.repository import ChromaVectorRepository

__all__ = ["ChromaVectorRepository", "EmbeddingSpaceFingerprint"]
