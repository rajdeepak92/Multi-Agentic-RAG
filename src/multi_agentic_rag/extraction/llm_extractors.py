"""LLM extraction interface placeholder for later phases."""

from __future__ import annotations

from typing import Protocol

from multi_agentic_rag.extraction.schemas import ExtractedFact


class LLMExtractor(Protocol):
    """Interface for future provider-backed extraction."""

    def extract(self, text: str) -> list[ExtractedFact]: ...


class DisabledLLMExtractor:
    """Phase 1 extractor that intentionally performs no LLM calls."""

    def extract(self, text: str) -> list[ExtractedFact]:
        return []
