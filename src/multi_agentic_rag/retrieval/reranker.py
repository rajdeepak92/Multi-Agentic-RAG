"""Reranker interface placeholder."""

from __future__ import annotations

from typing import Protocol


class Reranker(Protocol):
    """Interface for future BGE reranker integration."""

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]: ...


class NoopReranker:
    """Phase 1 reranker that preserves candidate order."""

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        return candidates
