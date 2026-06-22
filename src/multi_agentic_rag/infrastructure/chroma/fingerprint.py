"""Embedding-space fingerprint metadata for Chroma collections."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from multi_agentic_rag.config import Settings


class EmbeddingSpaceFingerprint(BaseModel):
    """Identity of the vector space stored in one Chroma collection."""

    provider: str
    model: str
    revision: str = "default"
    dimension: int
    normalization: str
    distance_metric: str
    prompt_profile: str = "default"
    hash: str = ""
    creation_time: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def from_settings(cls, settings: Settings) -> EmbeddingSpaceFingerprint:
        """Build a collection fingerprint from embedding settings."""

        fingerprint = cls(
            provider=settings.embedding_provider,
            model=settings.embedding_model,
            revision=settings.embedding_model_revision,
            dimension=settings.embedding_dimensions,
            normalization="l2" if settings.embedding_normalize else "none",
            distance_metric=settings.embedding_distance_metric,
            prompt_profile=settings.embedding_prompt_profile,
        )
        fingerprint.hash = fingerprint.compute_hash()
        return fingerprint

    def compute_hash(self) -> str:
        """Compute a stable hash excluding creation time."""

        payload = self.model_dump(mode="json", exclude={"hash", "creation_time"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def metadata(self) -> dict[str, str | int]:
        """Return Chroma-compatible collection metadata."""

        return {
            "qa_embedding_fingerprint": self.model_dump_json(),
            "qa_embedding_fingerprint_hash": self.hash,
            "qa_embedding_provider": self.provider,
            "qa_embedding_model": self.model,
            "qa_embedding_revision": self.revision,
            "qa_embedding_dimension": self.dimension,
            "qa_embedding_normalization": self.normalization,
            "qa_embedding_distance_metric": self.distance_metric,
            "qa_embedding_prompt_profile": self.prompt_profile,
        }

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> EmbeddingSpaceFingerprint | None:
        """Parse a fingerprint from Chroma metadata."""

        if not metadata:
            return None
        raw = metadata.get("qa_embedding_fingerprint")
        if not raw:
            return None
        parsed = cls.model_validate_json(str(raw))
        if not parsed.hash:
            parsed.hash = parsed.compute_hash()
        return parsed

    def compatible_with(self, other: EmbeddingSpaceFingerprint) -> bool:
        """Return whether two fingerprints refer to the same vector space."""

        return self.compute_hash() == other.compute_hash()
