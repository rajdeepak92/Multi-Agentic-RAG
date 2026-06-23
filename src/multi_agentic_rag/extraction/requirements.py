"""Segment-first requirement discovery."""

from __future__ import annotations

from multi_agentic_rag.domain import (
    ChunkRecord,
    RequirementCandidateRecord,
    RequirementCandidateStatus,
    RequirementDiscoveryResult,
    RequirementEvidenceRecord,
    RequirementRecord,
    SourceSegmentRecord,
)
from multi_agentic_rag.extraction.conflicts import detect_requirement_conflicts
from multi_agentic_rag.extraction.coverage import build_document_coverage_inventory
from multi_agentic_rag.extraction.rule_extractors import extract_requirement_ledger_from_chunks
from multi_agentic_rag.extraction.segments import segments_from_chunks
from multi_agentic_rag.identity import stable_id


def discover_requirements_from_chunks(chunks: list[ChunkRecord]) -> RequirementDiscoveryResult:
    """Compatibility wrapper that derives segments from chunks first."""

    return discover_requirements_from_segments(segments_from_chunks(chunks), chunks=chunks)


def discover_requirements_from_segments(
    segments: list[SourceSegmentRecord],
    *,
    chunks: list[ChunkRecord],
) -> RequirementDiscoveryResult:
    """Discover requirements from source segments and return one validated bundle."""

    if not chunks:
        return RequirementDiscoveryResult(
            discovery_id=stable_id("requirement_discovery", "empty"),
            document_version_id="",
            document_id="",
            system_name="",
            kb_name="default",
            version="",
        )
    requirements, evidence = extract_requirement_ledger_from_chunks(chunks)
    segment_by_chunk_id = {
        chunk_id: segment
        for segment in segments
        for chunk_id in segment.chunk_ids
    }
    requirements = [
        _attach_segment_metadata(requirement, segment_by_chunk_id.get(requirement.chunk_id))
        for requirement in requirements
    ]
    candidates = [
        _candidate_from_requirement(requirement, evidence, segment_by_chunk_id)
        for requirement in requirements
    ]
    conflicts = detect_requirement_conflicts(requirements)
    coverage = build_document_coverage_inventory(
        segments=segments,
        candidates=candidates,
        requirements=requirements,
        conflicts=conflicts,
    )
    first = chunks[0]
    return RequirementDiscoveryResult(
        discovery_id=stable_id(
            "requirement_discovery",
            first.system_name,
            first.kb_name,
            first.version,
            first.document_version_id,
            [chunk.chunk_id for chunk in chunks],
        ),
        document_version_id=first.document_version_id,
        document_id=first.document_id,
        system_name=first.system_name,
        kb_name=first.kb_name,
        version=first.version,
        segments=segments,
        candidates=candidates,
        requirements=requirements,
        requirement_evidence=evidence,
        coverage=coverage,
        conflicts=conflicts,
        metadata={"source": "deterministic_segment_discovery"},
    )


def _attach_segment_metadata(
    requirement: RequirementRecord,
    segment: SourceSegmentRecord | None,
) -> RequirementRecord:
    if segment is None:
        return requirement
    metadata = dict(requirement.metadata)
    metadata["segment_id"] = segment.segment_id
    metadata["segment_type"] = segment.segment_type
    return requirement.model_copy(update={"metadata": metadata})


def _candidate_from_requirement(
    requirement: RequirementRecord,
    evidence: list[RequirementEvidenceRecord],
    segment_by_chunk_id: dict[str, SourceSegmentRecord],
) -> RequirementCandidateRecord:
    segment = segment_by_chunk_id.get(requirement.chunk_id)
    primary_evidence = next(
        (item for item in evidence if item.requirement_pk == requirement.requirement_pk),
        None,
    )
    semantic_key = requirement.semantic_key or stable_id(
        "requirement_semantic_key",
        requirement.system_name,
        requirement.kb_name,
        requirement.version,
        requirement.requirement_type.value,
        requirement.canonical_id or requirement.requirement_id,
        requirement.normalized_text or requirement.text,
    )
    return RequirementCandidateRecord(
        candidate_id=stable_id(
            "requirement_candidate",
            requirement.document_version_id,
            segment.segment_id if segment else "",
            semantic_key,
        ),
        document_version_id=requirement.document_version_id,
        document_id=requirement.document_id,
        segment_id=segment.segment_id if segment else "",
        chunk_id=requirement.chunk_id,
        system_name=requirement.system_name,
        kb_name=requirement.kb_name,
        version=requirement.version,
        status=RequirementCandidateStatus.PROMOTED,
        requirement_type=requirement.requirement_type,
        canonical_id=requirement.canonical_id or requirement.requirement_id,
        proposed_requirement_id=requirement.requirement_id,
        text=requirement.text,
        normalized_text=requirement.normalized_text or requirement.text.strip().lower(),
        evidence_text=primary_evidence.evidence_text if primary_evidence else requirement.text,
        evidence_start_offset=primary_evidence.start_offset if primary_evidence else None,
        evidence_end_offset=primary_evidence.end_offset if primary_evidence else None,
        scope=requirement.category,
        confidence=requirement.confidence,
        semantic_key=semantic_key,
        metadata={"source": requirement.extraction_method},
    )
