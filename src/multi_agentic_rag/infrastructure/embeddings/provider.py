"""Embedding provider interfaces."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import time
import warnings
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from multi_agentic_rag.config import Settings
from multi_agentic_rag.exceptions import ProviderCapabilityError
from multi_agentic_rag.infrastructure.azure_openai_client import build_azure_openai_client
from multi_agentic_rag.runtime.device import resolve_device


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
        cache_dir: Path | None = None,
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
        self.cache_dir = cache_dir
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is None:
            _configure_hf_token(self.hf_token)
            with warnings.catch_warnings(), _suppress_sentence_transformers_cache_warning():
                warnings.filterwarnings(
                    "ignore",
                    message=r"The Transformer `cache_dir` argument is deprecated.*",
                )
                module = import_module("sentence_transformers")
                kwargs: dict[str, Any] = {"token": self.hf_token}
                if not _uses_auto_device(self.device):
                    kwargs["device"] = self.device
                if self.cache_dir is not None:
                    kwargs["cache_folder"] = str(self.cache_dir)
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


class AzureOpenAIEmbeddingProvider:
    """Azure OpenAI embedding provider with strict vector validation."""

    name = "azure_openai"

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
    ) -> None:
        self.settings = settings
        self.model = settings.embedding_deployment or settings.azure_openai_embedding_deployment
        self.deployment = self.model
        self.batch_size = settings.embedding_batch_size
        self.expected_dimension = settings.embedding_expected_dimension
        self.validated_dimension: int | None = None
        self._client = client
        self.request_diagnostics: list[dict[str, Any]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed documents through Azure OpenAI while preserving input order."""

        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors.extend(self._embed_batch(batch, batch_start=start))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """Embed one retrieval query through Azure OpenAI."""

        return self.embed_documents([text])[0]

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 - Chroma API
        """Expose the Chroma embedding-function protocol."""

        return self.embed_documents(input)

    def _embed_batch(self, texts: list[str], *, batch_start: int) -> list[list[float]]:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": self.deployment,
            "input": texts,
        }
        if self.expected_dimension is not None:
            kwargs["dimensions"] = self.expected_dimension
        started = time.perf_counter()
        try:
            response = client.embeddings.create(**kwargs)
        except Exception as exc:
            raise ProviderCapabilityError(
                f"Azure embedding request failed for deployment {self.deployment}: {exc}"
            ) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        data = list(getattr(response, "data", []) or [])
        if len(data) != len(texts):
            raise ProviderCapabilityError(
                f"Azure embedding response count {len(data)} did not match input count "
                f"{len(texts)}."
            )
        indexed_vectors: list[tuple[int, list[float]]] = []
        for offset, item in enumerate(data):
            index = int(getattr(item, "index", offset))
            vector = _as_float_vector(getattr(item, "embedding", []))
            self._validate_vector(vector)
            indexed_vectors.append((index, vector))
        indexed_vectors.sort(key=lambda item: item[0])
        self.request_diagnostics.append(
            {
                "client_class": type(client).__name__,
                "deployment": self.deployment,
                "endpoint_host": _azure_endpoint_host(self.settings.azure_openai_endpoint),
                "api_version": self.settings.azure_openai_api_version,
                "batch_start": batch_start,
                "batch_size": len(texts),
                "duration_ms": duration_ms,
                "usage": _usage_payload(getattr(response, "usage", None)),
                "validated_dimension": self.validated_dimension,
            }
        )
        return [vector for _, vector in indexed_vectors]

    def _validate_vector(self, vector: list[float]) -> None:
        if not vector:
            raise ProviderCapabilityError("Azure embedding response contained an empty vector.")
        dimension = len(vector)
        expected = self.expected_dimension or self.validated_dimension
        if expected is not None and dimension != expected:
            raise ProviderCapabilityError(
                f"Azure embedding dimension mismatch: expected {expected}, got {dimension}."
            )
        if self.validated_dimension is None:
            self.validated_dimension = dimension
        if any(math.isnan(value) or math.isinf(value) for value in vector):
            raise ProviderCapabilityError("Azure embedding vector contained NaN or infinity.")

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        self._client = build_azure_openai_client(self.settings)
        return self._client


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
    if settings.embedding_provider == "azure_openai":
        return AzureOpenAIEmbeddingProvider(settings)
    if settings.embedding_provider == "sentence_transformers":
        return SentenceTransformerEmbeddingProvider(
            settings.embedding_model,
            hf_token=settings.hf_token,
            device=resolve_device(settings.embedding_device, purpose="embedding").resolved,
            cache_dir=settings.sentence_transformers_home,
        )
    return HashEmbeddingProvider(
        dimensions=settings.embedding_dimensions,
        model=settings.embedding_model,
    )


def _as_float_vector(vector: Any) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(value) for value in vector]


def _usage_payload(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return cast(dict[str, Any], usage.model_dump(mode="json"))
    if isinstance(usage, dict):
        return cast(dict[str, Any], usage)
    return {
        name: getattr(usage, name)
        for name in ("prompt_tokens", "total_tokens", "input_tokens")
        if getattr(usage, name, None) is not None
    }


def _azure_endpoint_host(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    parsed = urlparse(endpoint.strip())
    return parsed.hostname


def _configure_hf_token(hf_token: str | None) -> None:
    if not hf_token:
        return
    os.environ.setdefault("HF_TOKEN", hf_token)
    os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", hf_token)


def _uses_auto_device(device: str) -> bool:
    return device.strip().lower() == "auto"


class _SentenceTransformerCacheWarningFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "The Transformer `cache_dir` argument is deprecated." not in record.getMessage()


class _suppress_sentence_transformers_cache_warning:
    """Temporarily hide the known internal cache_dir migration warning."""

    _LOGGER_NAMES = (
        "sentence_transformers.util.decorators",
        "sentence_transformers",
    )

    def __init__(self) -> None:
        self._filters: list[tuple[logging.Logger, logging.Filter]] = []

    def __enter__(self) -> None:
        for name in self._LOGGER_NAMES:
            logger = logging.getLogger(name)
            warning_filter = _SentenceTransformerCacheWarningFilter()
            logger.addFilter(warning_filter)
            self._filters.append((logger, warning_filter))

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        for logger, warning_filter in self._filters:
            logger.removeFilter(warning_filter)
