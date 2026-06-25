"""Typed LangGraph state for user-story generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from multi_agentic_rag.agents.user_stories.schemas import (
    EvidenceAssessment,
    EvidenceCandidate,
    RetrievalPlan,
    SourceRetrievalResponse,
    UserStoryGenerationRequest,
    UserStoryGenerationResult,
)
from multi_agentic_rag.domain import (
    EvidenceBundle,
    GeneratedUserStory,
    QualityValidationReport,
    RequirementCoverageRecord,
    RequirementEvidenceRecord,
    RequirementRecord,
)


class UserStoryGenerationState(TypedDict, total=False):
    """State exchanged by user-story graph nodes."""

    request: UserStoryGenerationRequest
    run_id: str
    run_dir: Path
    retrieval_plan: RetrievalPlan
    postgres_response: SourceRetrievalResponse
    chroma_response: SourceRetrievalResponse
    neo4j_response: SourceRetrievalResponse
    source_responses: list[SourceRetrievalResponse]
    ledger_requirements: list[RequirementRecord]
    ledger_evidence: list[RequirementEvidenceRecord]
    requirement_evidence_map: dict[str, dict[str, Any]]
    coverage_records: list[RequirementCoverageRecord]
    coverage_payload: dict[str, object]
    normalized_candidates: list[EvidenceCandidate]
    deduplicated_candidates: list[EvidenceCandidate]
    fused_results: list[EvidenceCandidate]
    reranked_evidence: list[EvidenceCandidate]
    evidence_assessment: EvidenceAssessment
    evidence_bundle: EvidenceBundle
    story_evidence_bundles: dict[str, EvidenceBundle]
    story_batch_requirement_ids: dict[str, list[str]]
    retrieval_round: int
    prompt: str
    story_group_plan: list[dict[str, object]]
    raw_model_output: str
    validated_stories: list[GeneratedUserStory]
    validation_reports: list[QualityValidationReport]
    validation_reports_by_story: dict[
        str,
        QualityValidationReport,
    ]
    validation_failures: list[str]
    story_validation_failures: dict[
        str,
        list[str],
    ]
    repair_story_ids: list[str]
    repair_requirement_ids: list[str]
    pending_validation_story_ids: list[str]
    artifact_paths: list[Path]
    debug_trace_path: Path
    generation_trace_path: Path
    validation_trace_path: Path
    generation_attempts_path: Path
    validation_attempts_path: Path
    framework_log_path: Path
    run_manifest_path: Path | None
    invalid_model_output_path: Path
    provider_errors_path: Path
    failure_error_type: str
    failure_stage: str
    trace_metadata: dict[str, str]
    retry_count: int
    next_action: str
    result: UserStoryGenerationResult
    errors: list[str]
    degraded_sources: list[str]
