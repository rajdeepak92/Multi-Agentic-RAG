"""Reranking service interfaces."""

from __future__ import annotations

import warnings
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import RetrievalResult
from multi_agentic_rag.infrastructure.embeddings.provider import (
    _configure_hf_token,
    _suppress_sentence_transformers_cache_warning,
)


class RerankingService(Protocol):
    """Reranker contract."""

    def rerank(self, query_text: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Rerank results.

        Args:
            query_text: Original user query.
            results: Candidate retrieval results after fusion.

        Returns:
            Results in final presentation order. Implementations may update
            scores and append source signals.
        """


class NoOpRerankingService:
    """Default reranker that preserves deterministic fused order."""

    def rerank(self, query_text: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Return results unchanged.

        Args:
            query_text: Original user query. It is accepted for interface
                compatibility and intentionally unused.
            results: Candidate retrieval results after fusion.

        Returns:
            The same results in the same order.
        """

        return results


class SentenceTransformerRerankingService:
    """Optional local cross-encoder reranker."""

    def __init__(
        self,
        model_name: str,
        *,
        hf_token: str | None = None,
        device: str = "auto",
        cache_dir: Path | None = None,
    ) -> None:
        """Initialize the lazy cross-encoder reranker.

        Args:
            model_name: Local or Hugging Face cross-encoder model name loaded on
                first rerank call.
            hf_token: Optional Hugging Face token used for Hub downloads.
            device: Target torch device. ``auto`` keeps sentence-transformers defaults.
        """

        self.model_name = model_name
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
                self._model = module.CrossEncoder(self.model_name, **kwargs)
        return self._model

    def rerank(self, query_text: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Rerank using a local cross-encoder.

        Args:
            query_text: Original user query.
            results: Candidate retrieval results after fusion.

        Returns:
            Results sorted by cross-encoder score with ``reranker`` added to the
            source signal list.
        """

        if not results:
            return []
        pairs = [(query_text, result.text) for result in results]
        scores = [float(score) for score in self._load().predict(pairs)]
        rescored = [
            result.model_copy(
                update={
                    "score": score,
                    "sources": [*result.sources, "reranker"],
                    "metadata": {**result.metadata, "reranker_score": score},
                }
            )
            for result, score in zip(results, scores, strict=True)
        ]
        return sorted(rescored, key=lambda item: (-item.score, item.chunk_id))


def select_reranker(settings: Settings) -> RerankingService:
    """Select the configured reranker.

    Args:
        settings: Runtime configuration containing reranker provider and model
            values.

    Returns:
        Cross-encoder reranker when explicitly configured, otherwise the no-op
        deterministic reranker.
    """

    settings.ensure_project_cache_paths()
    if settings.reranker_provider == "sentence_transformers" and settings.reranker_model:
        return SentenceTransformerRerankingService(
            settings.reranker_model,
            hf_token=settings.hf_token,
            device=settings.reranker_device,
            cache_dir=settings.sentence_transformers_home,
        )
    return NoOpRerankingService()


def _uses_auto_device(device: str) -> bool:
    return device.strip().lower() == "auto"
