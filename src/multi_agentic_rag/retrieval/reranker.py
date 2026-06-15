"""Reranker interface placeholder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from multi_agentic_rag.config import Settings, get_settings


class Reranker(Protocol):
    """Interface for future BGE reranker integration."""

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]: ...


class NoopReranker:
    """Phase 1 reranker that preserves candidate order."""

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        return candidates


@dataclass(frozen=True)
class RerankerSelection:
    """Selected reranker with provider metadata."""

    provider: str
    model_name: str
    reranker: Reranker
    reason: str


class BGEReranker:
    """Lazy BGE cross-encoder reranker for target GraphRAG mode."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        if not candidates:
            return []
        model = self._load_model()
        pairs = [(query, str(candidate.get("text") or candidate.get("document") or "")) for candidate in candidates]
        scores = model.predict(pairs)
        scored = [
            {**candidate, "rerank_score": float(score)}
            for candidate, score in zip(candidates, scores, strict=False)
        ]
        return sorted(scored, key=lambda item: item["rerank_score"], reverse=True)

    def check_ready(self, *, load_model: bool = False) -> tuple[bool, str]:
        try:
            from sentence_transformers import CrossEncoder  # noqa: F401
        except ModuleNotFoundError:
            return False, "sentence-transformers is required for BGE reranking."
        if load_model:
            try:
                self._load_model()
            except Exception as exc:  # pragma: no cover - model download/cache dependent
                return False, str(exc)
        return True, f"{self.model_name} is configured."

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model


def select_reranker(settings: Settings | None = None) -> RerankerSelection:
    """Select the reranker requested by settings."""

    settings = settings or get_settings()
    if settings.reranker_provider == "none":
        return RerankerSelection(
            provider="none",
            model_name="noop",
            reranker=NoopReranker(),
            reason="No-op reranker selected for local/default mode.",
        )
    if settings.reranker_provider == "huggingface":
        return RerankerSelection(
            provider="huggingface",
            model_name=settings.default_reranker_model,
            reranker=BGEReranker(settings.default_reranker_model),
            reason="BGE reranker selected for target GraphRAG mode.",
        )
    raise ValueError(f"Unsupported reranker provider: {settings.reranker_provider}")
