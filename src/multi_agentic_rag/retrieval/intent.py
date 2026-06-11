"""Rule-based query intent detection."""

from __future__ import annotations

from enum import Enum
import re


class QueryIntent(str, Enum):
    """Supported query intents."""

    CURRENT_TRUTH = "current_truth"
    HISTORICAL_TRUTH = "historical_truth"
    DELTA_ANALYSIS = "delta_analysis"
    COVERAGE_GENERATION = "coverage_generation"
    IMPACT_ANALYSIS = "impact_analysis"


def detect_intent(query: str) -> QueryIntent:
    """Detect query intent with deterministic keyword rules."""

    text = query.lower()
    if _contains_any(text, ("delta", "change", "changed", "difference", "diff")):
        return QueryIntent.DELTA_ANALYSIS
    if _contains_any(text, ("impact", "affected", "risk", "blast radius")):
        return QueryIntent.IMPACT_ANALYSIS
    if _contains_any(text, ("coverage", "test case", "test plan", "scenario")):
        return QueryIntent.COVERAGE_GENERATION
    if _contains_any(text, ("history", "historical", "previous", "old", "superseded", "v1")):
        return QueryIntent.HISTORICAL_TRUTH
    return QueryIntent.CURRENT_TRUTH


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    for token in tokens:
        pattern = r"(?<!\w)" + re.escape(token) + r"(?!\w)"
        if re.search(pattern, text):
            return True
    return False
