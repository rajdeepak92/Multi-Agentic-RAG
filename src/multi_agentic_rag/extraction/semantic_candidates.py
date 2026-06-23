"""Validation for strict LLM-proposed requirement candidates."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from multi_agentic_rag.domain import (
    RequirementCandidateRecord,
    RequirementCandidateStatus,
    RequirementType,
    SourceSegmentRecord,
)
from multi_agentic_rag.identity import stable_id


class SemanticRequirementCandidateDTO(BaseModel):
    """Strict LLM candidate DTO constrained to source-evidence values."""

    model_config = ConfigDict(extra="forbid")

    segment_id: str
    requirement_type: RequirementType
    text: str
    evidence_text: str
    scope: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


def validate_semantic_candidates(
    candidates: list[SemanticRequirementCandidateDTO],
    *,
    segments: list[SourceSegmentRecord],
    allowed_scopes: set[str] | None = None,
    minimum_confidence: float = 0.55,
) -> list[RequirementCandidateRecord]:
    """Validate LLM candidates against exact evidence spans and merge duplicates."""

    segment_by_id = {segment.segment_id: segment for segment in segments}
    merged: dict[str, RequirementCandidateRecord] = {}
    for candidate in candidates:
        segment = segment_by_id.get(candidate.segment_id)
        if segment is None:
            continue
        if allowed_scopes and candidate.scope and candidate.scope not in allowed_scopes:
            continue
        if candidate.confidence < minimum_confidence:
            continue
        start_offset = segment.text.find(candidate.evidence_text)
        if start_offset < 0:
            continue
        normalized_text = _normalize_text(candidate.text)
        if not normalized_text or _looks_unsupported(candidate.text):
            continue
        semantic_key = stable_id(
            "semantic_requirement",
            segment.system_name,
            segment.kb_name,
            segment.version,
            candidate.requirement_type.value,
            candidate.scope or "",
            normalized_text,
        )
        existing = merged.get(semantic_key)
        if existing is not None:
            if candidate.confidence > existing.confidence:
                merged[semantic_key] = existing.model_copy(
                    update={
                        "confidence": candidate.confidence,
                        "evidence_text": candidate.evidence_text,
                        "evidence_start_offset": start_offset,
                        "evidence_end_offset": start_offset + len(candidate.evidence_text),
                    }
                )
            continue
        merged[semantic_key] = RequirementCandidateRecord(
            candidate_id=stable_id(
                "requirement_candidate",
                segment.document_version_id,
                segment.segment_id,
                semantic_key,
            ),
            document_version_id=segment.document_version_id,
            document_id=segment.document_id,
            segment_id=segment.segment_id,
            chunk_id=segment.chunk_ids[0] if segment.chunk_ids else "",
            system_name=segment.system_name,
            kb_name=segment.kb_name,
            version=segment.version,
            status=RequirementCandidateStatus.VALIDATED,
            requirement_type=candidate.requirement_type,
            text=candidate.text.strip(),
            normalized_text=normalized_text,
            evidence_text=candidate.evidence_text,
            evidence_start_offset=start_offset,
            evidence_end_offset=start_offset + len(candidate.evidence_text),
            scope=candidate.scope,
            confidence=candidate.confidence,
            semantic_key=semantic_key,
            metadata={"source": "semantic_candidate"},
        )
    return list(merged.values())


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _looks_unsupported(text: str) -> bool:
    normalized = _normalize_text(text)
    return normalized in {"n/a", "none", "unknown", "tbd"} or len(normalized.split()) < 3
