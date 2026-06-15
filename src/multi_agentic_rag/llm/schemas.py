"""Structured LLM decision schemas.

The LLM returns planning decisions only. Python agents perform all mutations.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class IntentDecision(BaseModel):
    """Structured routing decision for natural-language MARAG tasks."""

    intent: str
    system_name: str | None = None
    version: str | None = None
    scenario_count: int | None = None
    execution_mode: str | None = None
    coverage_focus: str | None = None
    artifact_types: list[str] = Field(default_factory=list)
    execute: bool | None = None
    force_run_all: bool = False
    robot_enabled: bool | None = None
    needs_device_config: bool = False
    next_agent: str | None = None
    missing_inputs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""


class ExtractionFallbackFact(BaseModel):
    """LLM fallback fact tied to retrieved source evidence."""

    fact_key: str
    fact_type: str
    value: str
    unit: str | None = None
    requirement_id: str | None = None
    evidence: str


class ExtractionFallbackResult(BaseModel):
    """Structured facts returned by optional LLM extraction fallback."""

    facts: list[ExtractionFallbackFact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ScenarioPlanItem(BaseModel):
    """Scenario planning decision for one candidate test."""

    requirement_id: str
    scenario: str
    priority: str = "medium"
    impact_status: str = "new_required"
    reason: str = ""


class ScenarioPlan(BaseModel):
    """LLM-assisted scenario selection plan."""

    scenarios: list[ScenarioPlanItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnswerDraft(BaseModel):
    """Evidence-bounded answer draft."""

    answer: str
    used_evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
