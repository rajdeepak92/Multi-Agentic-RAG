"""Coverage inventory helpers for requirement discovery."""

from __future__ import annotations

from collections import Counter

from multi_agentic_rag.domain import (
    DocumentCoverageRecord,
    DocumentCoverageStatus,
    RequirementCandidateRecord,
    RequirementConflictRecord,
    RequirementRecord,
    SourceSegmentRecord,
)
from multi_agentic_rag.identity import stable_id


def build_document_coverage_inventory(
    *,
    segments: list[SourceSegmentRecord],
    candidates: list[RequirementCandidateRecord],
    requirements: list[RequirementRecord],
    conflicts: list[RequirementConflictRecord] | None = None,
) -> list[DocumentCoverageRecord]:
    """Build deterministic per-segment discovery coverage rows."""

    candidates_by_segment = Counter(candidate.segment_id for candidate in candidates)
    requirements_by_segment = Counter(
        str(requirement.metadata.get("segment_id") or "") for requirement in requirements
    )
    conflicts_by_segment = Counter(
        str(segment_id)
        for conflict in conflicts or []
        for segment_id in conflict.metadata.get("segment_ids", [])
        if segment_id
    )
    records: list[DocumentCoverageRecord] = []
    for segment in segments:
        requirement_count = requirements_by_segment.get(segment.segment_id, 0)
        candidate_count = candidates_by_segment.get(segment.segment_id, 0)
        conflict_count = conflicts_by_segment.get(segment.segment_id, 0)
        status = (
            DocumentCoverageStatus.COMPLETE
            if requirement_count or candidate_count
            else DocumentCoverageStatus.UNKNOWN
        )
        records.append(
            DocumentCoverageRecord(
                coverage_inventory_id=stable_id(
                    "coverage_inventory",
                    segment.document_version_id,
                    segment.segment_id,
                ),
                document_version_id=segment.document_version_id,
                document_id=segment.document_id,
                system_name=segment.system_name,
                kb_name=segment.kb_name,
                version=segment.version,
                segment_id=segment.segment_id,
                section_title=segment.section_title,
                coverage_status=status,
                requirement_count=requirement_count,
                candidate_count=candidate_count,
                conflict_count=conflict_count,
                notes=[] if status is DocumentCoverageStatus.COMPLETE else ["no requirement text"],
                metadata={"chunk_ids": segment.chunk_ids},
            )
        )
    return records
