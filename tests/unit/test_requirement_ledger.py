from __future__ import annotations

from collections import Counter

from multi_agentic_rag.domain import ChunkRecord, DocumentStatus, RequirementType
from multi_agentic_rag.extraction.requirements import discover_requirements_from_chunks
from multi_agentic_rag.extraction.rule_extractors import (
    extract_requirement_ledger_from_chunks,
    extract_requirements_from_chunk,
)
from multi_agentic_rag.extraction.segments import segments_from_chunks
from multi_agentic_rag.extraction.semantic_candidates import (
    SemanticRequirementCandidateDTO,
    validate_semantic_candidates,
)
from multi_agentic_rag.requirements_ledger import (
    RequirementQueryIntent,
    build_coverage_records,
    classify_requirement_query,
    coverage_payload,
    render_requirement_answer,
    requirement_inventory_payload,
)


def test_siimcs_requirement_ledger_extracts_complete_inventory() -> None:
    requirements, evidence = extract_requirement_ledger_from_chunks([_chunk(_siimcs_text())])

    counts = Counter(requirement.requirement_type for requirement in requirements)

    assert counts[RequirementType.BUSINESS_RULE] == 40
    assert counts[RequirementType.NON_FUNCTIONAL] == 7
    assert counts[RequirementType.AUTOMATION_RULE] == 5
    assert counts[RequirementType.ACCEPTANCE_CRITERION] == 9
    assert counts[RequirementType.DEFINITION_OF_DONE] == 6
    br_ids = {
        requirement.requirement_id
        for requirement in requirements
        if requirement.requirement_id.startswith("BR-")
    }
    assert br_ids == set(_explicit_br_ids())
    assert len(evidence) >= len(requirements)
    assert all(item.evidence_text for item in evidence)
    assert all(item.requirement_pk for item in evidence)


def test_requirement_id_variants_are_normalized() -> None:
    records = extract_requirements_from_chunk(
        _chunk(
            """
            BR-COM 001 The controller shall support spaced IDs.
            BR-COM–002 The controller shall support en dash IDs.
            BR-COM—003 The controller shall support em dash IDs.
            BR-COM_004 The controller shall support underscore IDs.
            AC-001 Acceptance shall be verified.
            """,
        )
    )

    assert [record.requirement_id for record in records] == [
        "BR-COM-001",
        "BR-COM-002",
        "BR-COM-003",
        "BR-COM-004",
        "AC-001",
    ]


def test_repeated_evidence_does_not_create_duplicate_ledger_records() -> None:
    first = _chunk("BR-SEN-001 The controller shall collect sensor readings.", chunk_id="a")
    second = _chunk("BR-SEN-001 The controller shall collect sensor readings.", chunk_id="b")

    requirements, evidence = extract_requirement_ledger_from_chunks([first, second])

    assert [requirement.canonical_id for requirement in requirements] == ["BR-SEN-001"]
    assert len(evidence) == 2
    assert {item.chunk_id for item in evidence} == {"a", "b"}


def test_segment_first_discovery_returns_validated_bundle() -> None:
    result = discover_requirements_from_chunks(
        [_chunk("BR-SEN-001 The controller shall collect sensor readings.")]
    )

    assert result.segments
    assert result.candidates
    assert result.requirements[0].requirement_type == RequirementType.BUSINESS_RULE
    assert result.coverage[0].coverage_status.value == "complete"
    assert result.requirements[0].metadata["segment_id"] == result.segments[0].segment_id


def test_semantic_candidate_validation_rejects_unsupported_and_merges_duplicates() -> None:
    segment = segments_from_chunks(
        [_chunk("The system shall retain latest good data during outages.")]
    )[0]
    valid = SemanticRequirementCandidateDTO(
        segment_id=segment.segment_id,
        requirement_type=RequirementType.NON_FUNCTIONAL,
        text="The system shall retain latest good data during outages.",
        evidence_text="shall retain latest good data",
        scope="Reliability",
        confidence=0.9,
    )
    duplicate = valid.model_copy(update={"confidence": 0.8})
    unsupported = SemanticRequirementCandidateDTO(
        segment_id=segment.segment_id,
        requirement_type=RequirementType.NON_FUNCTIONAL,
        text="TBD",
        evidence_text="shall retain latest good data",
        scope="Reliability",
        confidence=0.9,
    )
    missing_evidence = valid.model_copy(update={"evidence_text": "not in segment"})

    candidates = validate_semantic_candidates(
        [valid, duplicate, unsupported, missing_evidence],
        segments=[segment],
    )

    assert len(candidates) == 1
    assert candidates[0].evidence_start_offset is not None
    assert candidates[0].confidence == 0.9


def test_exhaustive_requirement_answer_uses_full_ledger() -> None:
    requirements, evidence = extract_requirement_ledger_from_chunks([_chunk(_siimcs_text())])
    payload = requirement_inventory_payload(
        requirements,
        evidence,
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
    )

    answer = render_requirement_answer(payload, [])

    assert classify_requirement_query("Summarize all requirements and business rules.") is (
        RequirementQueryIntent.EXHAUSTIVE_REQUIREMENT_QUERY
    )
    assert payload["counts_by_type"]["business_rule"] == 40
    assert payload["counts_by_type"]["non_functional"] == 7
    assert "total records: 70" in answer
    assert "Business Rule:" in answer
    assert "Non Functional:" in answer
    assert "Automation Rule:" in answer
    assert "Acceptance Criterion:" in answer
    assert all(requirement_id in answer for requirement_id in _explicit_br_ids())


def test_coverage_matrix_marks_missing_required_items() -> None:
    requirements, _ = extract_requirement_ledger_from_chunks([_chunk(_siimcs_text())])
    selected = [
        requirement
        for requirement in requirements
        if requirement.canonical_id in {"BR-SEN-001", "BR-SEN-002"}
    ]

    records = build_coverage_records(
        requirements=selected,
        story_requirement_ids={"US-001": ["BR-SEN-001"]},
    )
    matrix = coverage_payload(requirements=selected, coverage=records)

    statuses = {row["canonical_id"]: row["coverage_status"] for row in matrix["rows"]}
    assert statuses == {"BR-SEN-001": "covered", "BR-SEN-002": "missing"}


def _chunk(text: str, *, chunk_id: str = "chunk-1") -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        document_version_id="dv-1",
        document_id="doc-1",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        status=DocumentStatus.ACTIVE,
        source_name="SIIMCS_BRD_V1.pdf",
        page=1,
        section_title="SIIMCS",
        chunk_index=0,
        content_hash=f"hash-{chunk_id}",
        text=text,
    )


def _explicit_br_ids() -> list[str]:
    groups = {
        "SEN": 5,
        "COM": 5,
        "CFG": 5,
        "VAL": 4,
        "OFF": 4,
        "ALT": 5,
        "HLT": 2,
        "DQ": 3,
        "APP": 3,
        "SEC": 4,
    }
    return [
        f"BR-{area}-{index:03d}"
        for area, count in groups.items()
        for index in range(1, count + 1)
    ]


def _siimcs_text() -> str:
    explicit_lines = "\n".join(
        f"{requirement_id} The controller shall satisfy {requirement_id} safely."
        for requirement_id in _explicit_br_ids()
    )
    ac_lines = "\n".join(
        f"AC-{index:03d} Acceptance shall verify scenario {index} successfully."
        for index in range(1, 10)
    )
    dod_lines = "\n".join(
        f"Delivery item {index} shall be tested and approved before release."
        for index in range(1, 7)
    )
    return f"""
    3.1 In Scope
    Sensor monitoring is in scope.
    Alert notification is in scope.
    3.2 Out of Scope
    Manual calibration tools are out of scope.
    4. Stakeholders

    6. Functional Requirements
    ID Requirement
    {explicit_lines}

    6.8 Rule-Based Automation
    Condition
    Safety
    Level
    Expected Action
    Gas concentration exceeds high-high threshold
    Critical
    perform emergency shutdown.
    Temperature exceeds configured maximum
    High
    trigger alert notification.
    Pressure falls below configured minimum
    Medium
    mark device as degraded.
    Vibration exceeds safety threshold
    High
    stop actuator command.
    Communication failure persists
    Low
    retain latest good data.
    6.9 Sensor and Actuator Data Sheet

    7. Non-Functional Requirements
    Area Requirement
    Reliability Monitoring shall continue safely when one sensor fails.
    Availability Latest good data shall remain available during outages.
    Performance Polling, alerting and synchronization shall complete quickly.
    Scalability The design shall support additional configured sensors.
    Maintainability Thresholds, rules and polling settings shall be configurable.
    Security Access to data and control actions shall be approved.
    Embedded Safety The controller shall operate safely without cloud connectivity.

    8. Acceptance Criteria
    ID Acceptance Criteria
    {ac_lines}

    The feature is complete when:
    {dod_lines}
    """
