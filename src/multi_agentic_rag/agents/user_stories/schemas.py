"""Schemas for LangGraph user-story generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from multi_agentic_rag.common import RetrievalSourceName
from multi_agentic_rag.domain import GeneratedUserStory, RetrievalResult


class UserStoryGenerationRequest(BaseModel):
    """Input scope for user-story generation from an ingested knowledge base."""

    system: str
    version: str
    kb: str = "default"


class RetrievalPlan(BaseModel):
    """Source-specific retrieval plan produced by the reasoning provider."""

    lexical_queries: list[str] = Field(default_factory=list)
    semantic_queries: list[str] = Field(default_factory=list)
    graph_entities: list[str] = Field(default_factory=list)
    graph_relationships: list[str] = Field(default_factory=list)
    target_requirement_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class SourceRetrievalResponse(BaseModel):
    """One retrieval-source response envelope preserved through fan-in."""

    source: RetrievalSourceName
    status: Literal["success", "empty", "failed"]
    queries: list[str] = Field(default_factory=list)
    candidates: list[RetrievalResult] = Field(default_factory=list)
    duration_ms: int = 0
    error: str | None = None


class SourceHit(BaseModel):
    """Source-specific rank and score for one evidence hit."""

    source: RetrievalSourceName
    rank: int
    raw_score: float | None = None
    query: str
    evidence_path: list[str] = Field(default_factory=list)


class EvidenceCandidate(BaseModel):
    """Normalized, provenance-preserving retrieval candidate."""

    result_id: str
    document_id: str | None = None
    document_version: str | None = None
    chunk_id: str | None = None
    fact_id: str | None = None
    requirement_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    text: str
    page_number: int | None = None
    source_name: str | None = None
    active_status: str | None = None
    source_hits: list[SourceHit] = Field(default_factory=list)
    fused_score: float | None = None
    reranker_score: float | None = None
    final_rank: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceAssessment(BaseModel):
    """Reasoned sufficiency judgement over selected evidence."""

    sufficient: bool
    covered_requirement_ids: list[str] = Field(default_factory=list)
    missing_topics: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    unsupported_claim_risks: list[str] = Field(default_factory=list)
    refined_queries: RetrievalPlan | None = None
    rationale: str = ""


class UserStoryGenerationResult(BaseModel):
    """Typed final result for user-story generation."""

    status: Literal["succeeded", "failed"]
    run_id: str
    messages: list[str] = Field(default_factory=list)
    artifact_paths: list[Path] = Field(default_factory=list)
    debug_trace_path: Path | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    degraded_sources: list[RetrievalSourceName] = Field(default_factory=list)
    stories: list[GeneratedUserStory] = Field(default_factory=list)
