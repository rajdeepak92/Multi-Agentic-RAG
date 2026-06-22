"""Embedding provider interfaces."""

from __future__ import annotations

import hashlib
import os
from importlib import import_module
from typing import Any, Protocol

from multi_agentic_rag.config import Settings


class EmbeddingProvider(Protocol):
    """Minimal embedding provider contract."""

    name: str
    model: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed source chunks or documents.

        Args:
            texts: Ordered text inputs to embed.

        Returns:
            One embedding vector per input text, in the same order.
        """

    def embed_query(self, text: str) -> list[float]:
        """Embed one retrieval query.

        Args:
            text: Query text supplied by retrieval.

        Returns:
            Embedding vector for the query.
        """


class HashEmbeddingProvider:
    """Deterministic offline embedding provider."""

    name = "hash"

    def __init__(self, *, dimensions: int = 384, model: str = "multi-agentic-rag-hash") -> None:
        """Initialize the deterministic embedding provider.

        Args:
            dimensions: Number of float values to emit per embedding.
            model: Logical model name saved in Chroma metadata.
        """

        self.dimensions = dimensions
        self.model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed documents deterministically.

        Args:
            texts: Ordered text inputs to convert into stable hash vectors.

        Returns:
            One deterministic vector per input text.
        """

        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """Embed one query deterministically.

        Args:
            text: Query text to convert into a stable hash vector.

        Returns:
            Deterministic vector for the query.
        """

        return self._embed(text)

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 - Chroma API
        """Expose the Chroma embedding-function protocol."""

        return self.embed_documents(input)

    def is_legacy(self) -> bool:
        """Tell Chroma this embedding function exposes current config hooks."""

        return False

    @staticmethod
    def supported_spaces() -> list[str]:
        """Return vector spaces supported by the deterministic embedding."""

        return ["cosine"]

    @staticmethod
    def default_space() -> str:
        """Return the default vector space."""

        return "cosine"

    @staticmethod
    def name_for_chroma() -> str:
        """Return a stable Chroma embedding-function name."""

        return "multi_agentic_rag_hash_embedding"

    def get_config(self) -> dict[str, int | str]:
        """Return serializable Chroma embedding-function configuration."""

        return {"dimensions": self.dimensions, "model": self.model}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> HashEmbeddingProvider:
        """Rebuild from Chroma collection config.

        Args:
            config: Serialized embedding-function configuration saved by Chroma.

        Returns:
            Hash embedding provider matching the persisted dimensions and model.
        """

        return HashEmbeddingProvider(
            dimensions=int(config.get("dimensions", 384)),
            model=str(config.get("model", "multi-agentic-rag-hash")),
        )

    def _embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        while len(values) < self.dimensions:
            for byte in digest:
                values.append((byte / 255.0) - 0.5)
                if len(values) == self.dimensions:
                    break
            digest = hashlib.sha256(digest).digest()
        return values


class SentenceTransformerEmbeddingProvider:
    """Sentence-transformer embedding provider loaded lazily."""

    name = "sentence_transformers"

    def __init__(
        self,
        model: str,
        *,
        hf_token: str | None = None,
        device: str = "auto",
    ) -> None:
        """Initialize a lazily loaded sentence-transformer provider.

        Args:
            model: Local or Hugging Face model name passed to
                ``SentenceTransformer`` on first use.
            hf_token: Optional Hugging Face token used for Hub downloads.
            device: Target torch device. ``auto`` keeps sentence-transformers defaults.
        """

        self.model = model
        self.hf_token = hf_token
        self.device = device
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is None:
            _configure_hf_token(self.hf_token)
            module = import_module("sentence_transformers")
            kwargs: dict[str, str | None] = {"token": self.hf_token}
            if not _uses_auto_device(self.device):
                kwargs["device"] = self.device
            self._model = module.SentenceTransformer(self.model, **kwargs)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed documents with sentence-transformers.

        Args:
            texts: Ordered text inputs to encode with the local model.

        Returns:
            Normalized dense vectors in the same order as the inputs.
        """

        return [
            _as_float_vector(vector)
            for vector in self._load().encode(texts, normalize_embeddings=True)
        ]

    def embed_query(self, text: str) -> list[float]:
        """Embed one query with sentence-transformers.

        Args:
            text: Query text to encode with the local model.

        Returns:
            Normalized dense vector for the query.
        """

        return self.embed_documents([text])[0]

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 - Chroma API
        """Expose the Chroma embedding-function protocol."""

        return self.embed_documents(input)


def select_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Select the configured embedding provider.

    Args:
        settings: Runtime configuration with provider name, model name, and hash
            embedding dimensions.

    Returns:
        Embedding provider implementation. Unknown provider values fall back to
        the deterministic hash provider.
    """

    settings.ensure_project_cache_paths()
    if settings.embedding_provider == "sentence_transformers":
        return SentenceTransformerEmbeddingProvider(
            settings.embedding_model,
            hf_token=settings.hf_token,
            device=settings.embedding_device,
        )
    return HashEmbeddingProvider(
        dimensions=settings.embedding_dimensions,
        model=settings.embedding_model,
    )


def _as_float_vector(vector: Any) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(value) for value in vector]


def _configure_hf_token(hf_token: str | None) -> None:
    if not hf_token:
        return
    os.environ.setdefault("HF_TOKEN", hf_token)
    os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", hf_token)


def _uses_auto_device(device: str) -> bool:
    return device.strip().lower() == "auto"
