"""Information extraction interfaces and implementations."""

from multi_agentic_rag.extraction.rule_extractors import extract_facts_from_chunk, extract_facts_from_text

__all__ = ["extract_facts_from_chunk", "extract_facts_from_text"]
