"""Extraction helpers."""

from multi_agentic_rag.extraction.requirements import (
    discover_requirements_from_chunks,
    discover_requirements_from_segments,
)
from multi_agentic_rag.extraction.rule_extractors import (
    ExtractedFact,
    extract_facts_from_chunk,
    extract_facts_from_text,
)
from multi_agentic_rag.extraction.segments import segments_from_chunks, segments_from_pages

__all__ = [
    "ExtractedFact",
    "discover_requirements_from_chunks",
    "discover_requirements_from_segments",
    "extract_facts_from_chunk",
    "extract_facts_from_text",
    "segments_from_chunks",
    "segments_from_pages",
]
