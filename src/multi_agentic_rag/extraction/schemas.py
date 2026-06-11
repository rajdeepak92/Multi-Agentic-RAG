"""Extraction schemas independent of persistence."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExtractedFact(BaseModel):
    """Raw deterministic extraction result before registry IDs are assigned."""

    fact_type: str
    fact_key: str
    value: str
    evidence: str
    unit: str | None = None
    requirement_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
