"""Requirement conflict detection."""

from __future__ import annotations

from collections import defaultdict

from multi_agentic_rag.domain import RequirementConflictRecord, RequirementRecord
from multi_agentic_rag.identity import stable_id


def detect_requirement_conflicts(
    requirements: list[RequirementRecord],
) -> list[RequirementConflictRecord]:
    """Preserve conflicting claims that share a semantic key but differ in text."""

    by_key: dict[str, list[RequirementRecord]] = defaultdict(list)
    for requirement in requirements:
        semantic_key = (
            requirement.semantic_key
            or requirement.canonical_id
            or requirement.requirement_id
        )
        by_key[semantic_key].append(requirement)
    conflicts: list[RequirementConflictRecord] = []
    for semantic_key, grouped in by_key.items():
        normalized_claims = {
            (requirement.normalized_text or requirement.text).strip().lower()
            for requirement in grouped
        }
        if len(grouped) < 2 or len(normalized_claims) < 2:
            continue
        first = grouped[0]
        conflicts.append(
            RequirementConflictRecord(
                conflict_id=stable_id(
                    "requirement_conflict",
                    first.system_name,
                    first.kb_name,
                    first.version,
                    semantic_key,
                    sorted(normalized_claims),
                ),
                system_name=first.system_name,
                kb_name=first.kb_name,
                version=first.version,
                document_version_id=first.document_version_id,
                semantic_key=semantic_key,
                requirement_pks=[
                    requirement.requirement_pk
                    for requirement in grouped
                    if requirement.requirement_pk
                ],
                claims=[requirement.text for requirement in grouped],
                summary="Unresolved conflicting requirement claims were found.",
                metadata={
                    "segment_ids": sorted(
                        {
                            str(requirement.metadata.get("segment_id"))
                            for requirement in grouped
                            if requirement.metadata.get("segment_id")
                        }
                    )
                },
            )
        )
    return conflicts
