"""Embedding provider selection for vector stores."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from multi_agentic_rag.config import Settings
from multi_agentic_rag.storage.registry import require_local_dev_mode
from multi_agentic_rag.storage.chroma_store import HashEmbeddingFunction
from multi_agentic_rag.utils.paths import resolve_path


@dataclass(frozen=True)
class EmbeddingSelection:
    """Selected embedding function plus provider metadata."""

    provider: str
    model_name: str
    embedding_function: Any
    reason: str


class HuggingFaceEmbeddingFunction:
    """Lazy sentence-transformers embedding function for real retrieval."""

    def __init__(
        self,
        *,
        model_name: str,
        cache_folder: str | Path | None = None,
        token: str | None = None,
        normalize_embeddings: bool = True,
    ) -> None:
        self.model_name = model_name
        self.cache_folder = str(resolve_path(cache_folder)) if cache_folder else None
        self.token = token
        self.normalize_embeddings = normalize_embeddings
        self._model: Any | None = None

    def __call__(self, input: Iterable[str]) -> list[list[float]]:  # noqa: A002 - Chroma API
        return self.embed_documents(input)

    def embed_query(self, input: str | Iterable[str]):  # noqa: A002 - Chroma API
        """Embed query text for vector stores."""

        if isinstance(input, str):
            return self._encode([input])[0]
        return self._encode(list(input))

    def embed_documents(self, input: Iterable[str]) -> list[list[float]]:  # noqa: A002
        """Embed document strings for Chroma and Weaviate."""

        return self._encode(list(input))

    def is_legacy(self) -> bool:
        """Tell Chroma this embedding function exposes current config hooks."""

        return False

    @staticmethod
    def supported_spaces() -> list[str]:
        """Return vector spaces supported by this embedding."""

        return ["cosine"]

    @staticmethod
    def default_space() -> str:
        """Return the default Chroma vector space."""

        return "cosine"

    @staticmethod
    def name() -> str:
        """Return a stable Chroma embedding-function name."""

        return "multi_agentic_rag_huggingface_embedding"

    def get_config(self) -> dict[str, str | bool | None]:
        """Return serializable Chroma embedding-function configuration."""

        return {
            "model_name": self.model_name,
            "cache_folder": self.cache_folder,
            "normalize_embeddings": self.normalize_embeddings,
        }

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "HuggingFaceEmbeddingFunction":
        """Rebuild the embedding function from Chroma collection config."""

        return HuggingFaceEmbeddingFunction(
            model_name=str(config.get("model_name", "BAAI/bge-m3")),
            cache_folder=config.get("cache_folder"),
            normalize_embeddings=bool(config.get("normalize_embeddings", True)),
        )

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        vectors = model.encode(
            texts,
            normalize_embeddings=self.normalize_embeddings,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ModuleNotFoundError as exc:  # pragma: no cover - dependency optional at runtime
                raise RuntimeError(
                    "EMBEDDING_PROVIDER=huggingface requires sentence-transformers. "
                    "Run `uv sync --locked` and ensure the model cache is available."
                ) from exc
            kwargs: dict[str, Any] = {}
            if self.cache_folder:
                kwargs["cache_folder"] = self.cache_folder
            if self.token:
                kwargs["token"] = self.token
            try:
                self._model = SentenceTransformer(self.model_name, **kwargs)
            except TypeError:
                kwargs.pop("token", None)
                self._model = SentenceTransformer(self.model_name, **kwargs)
        return self._model


def select_embedding_function(settings: Settings) -> EmbeddingSelection:
    """Select the embedding function requested by settings."""

    provider = settings.embedding_provider.lower()
    if provider == "hash":
        require_local_dev_mode(settings, "EMBEDDING_PROVIDER=hash")
        return EmbeddingSelection(
            provider="hash",
            model_name="multi_agentic_rag_hash_embedding",
            embedding_function=HashEmbeddingFunction(
                dimensions=settings.hash_embedding_dimensions
            ),
            reason="Deterministic test/offline embedding fallback selected.",
        )
    if provider == "huggingface":
        return EmbeddingSelection(
            provider="huggingface",
            model_name=settings.default_embedding_model,
            embedding_function=HuggingFaceEmbeddingFunction(
                model_name=settings.default_embedding_model,
                cache_folder=settings.hf_home,
                token=settings.hf_token,
            ),
            reason="Open-source BGE embedding provider selected.",
        )
    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")
