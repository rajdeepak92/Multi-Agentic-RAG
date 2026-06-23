"""Deterministic rule-based extractors for engineering GraphRAG evidence."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from multi_agentic_rag.domain import (
    ChunkRecord,
    FactRecord,
    RequirementEvidenceRecord,
    RequirementRecord,
    RequirementType,
)
from multi_agentic_rag.utils.hashing import stable_id

REQUIREMENT_RE = re.compile(
    r"\b(?:(?:REQ|BRD|SRS|FRS|API|UC|AC)\s*[-_\u2010-\u2015]?\s*\d+(?:\.\d+)?|"
    r"BR\s*[-_\u2010-\u2015_]?\s*[A-Z]{2,10}\s*[-_\u2010-\u2015_]?\s*\d+(?:\.\d+)?)\b",
    re.I,
)
EXPLICIT_REQUIREMENT_RE = re.compile(
    r"\b(?P<br>BR\s*[-_\u2010-\u2015_]?\s*(?P<br_area>[A-Z]{2,10})"
    r"\s*[-_\u2010-\u2015_]?\s*(?P<br_number>\d{1,4}(?:\.\d+)?))\b|"
    r"\b(?P<simple>(?P<simple_prefix>REQ|SRS|FRS|AC|BRD)\s*[-_\u2010-\u2015_]?"
    r"\s*(?P<simple_number>\d{1,4}(?:\.\d+)?))\b",
    re.I,
)
NFR_AREAS = (
    "Reliability",
    "Availability",
    "Performance",
    "Scalability",
    "Maintainability",
    "Security",
    "Embedded Safety",
)
AUTOMATION_SAFETY_LEVELS = {"Low", "Medium", "High", "Critical"}
EXHAUSTIVE_SECTION_FOOTER_RE = re.compile(
    r"\bSIIMCS_BRD_V\d+\.md\b|\d{4}-\d{2}-\d{2}|\d+\s*/\s*\d+"
)
PROTOCOLS = ("Modbus", "MQTT", "CAN", "REST")
SENSORS = (
    "temperature",
    "pressure",
    "vibration",
    "humidity",
    "flow",
    "voltage",
    "current",
    "speed",
    "level",
)
SENSOR_RE = "|".join(re.escape(sensor) for sensor in SENSORS)
UNIT_RE = (
    r"(?:deg\s*C|C|F|K|bar|psi|Pa|kPa|MPa|%|percent|rpm|Hz|mA|A|V|W|"
    r"mm/s|m/s|g|ms|s|seconds?)"
)
THRESHOLD_PATTERNS = [
    re.compile(
        rf"\b(?P<sensor>{SENSOR_RE})\b.{{0,80}}?"
        rf"\b(?:threshold|limit|setpoint|must not exceed|shall not exceed|maximum|max|min)\b"
        rf".{{0,40}}?(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>{UNIT_RE})?\b",
        re.I,
    ),
    re.compile(
        rf"\b(?:threshold|limit|setpoint|must not exceed|shall not exceed|maximum|max|min)\b"
        rf".{{0,80}}?\b(?P<sensor>{SENSOR_RE})\b"
        rf".{{0,40}}?(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>{UNIT_RE})?\b",
        re.I,
    ),
]
DEVICE_RE = re.compile(
    r"\b(?i:(?:device|controller|gateway|plc|rtu|ecu|module|unit|sensor node))\s+"
    r"(?P<name>[A-Z][A-Za-z0-9_-]{1,40})\b"
)
MQTT_TOPIC_RE = re.compile(
    r"\b(?:MQTT\s+topic|topic)\s+(?P<topic>[/A-Za-z0-9_+.#{}-]{3,})",
    re.I,
)
REST_ENDPOINT_RE = re.compile(
    r"\b(?P<method>GET|POST|PUT|PATCH|DELETE)\s+(?P<path>/[A-Za-z0-9_./{}:-]+)\b",
    re.I,
)
CAN_ID_RE = re.compile(r"\bCAN(?:\s+ID|\s+identifier)?\s*(?P<can_id>0x[0-9A-Fa-f]+|\d{2,})\b", re.I)
MODBUS_REGISTER_RE = re.compile(
    r"\b(?:Modbus\s+)?(?P<kind>register|coil)\s*(?P<address>\d{1,5})\b", re.I
)


class ExtractedFact(BaseModel):
    """Extractor output before lineage is attached.

    Attributes:
        fact_type: Extractor category.
        fact_key: Semantic key used for dedupe and deltas.
        value: Extracted fact value.
        evidence: Source-grounded evidence snippet.
        unit: Optional unit associated with numeric values.
        requirement_id: Nearby requirement identifier when found.
        metadata: Extractor-specific structured metadata.
    """

    fact_type: str
    fact_key: str
    value: str
    evidence: str
    unit: str | None = None
    requirement_id: str | None = None
    metadata: dict[str, str | int | None] = Field(default_factory=dict)


class ExtractedRequirement(BaseModel):
    """Requirement ledger candidate before cross-chunk de-duplication."""

    canonical_id: str
    requirement_id: str
    requirement_type: RequirementType
    category: str | None = None
    title: str | None = None
    text: str
    normalized_text: str
    chunk: ChunkRecord
    start_offset: int | None = None
    end_offset: int | None = None
    section_title: str | None = None
    story_driving: bool = True
    coverage_required: bool = True
    extraction_method: str = "deterministic"
    confidence: float = 1.0
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


def extract_facts_from_text(text: str) -> list[ExtractedFact]:
    """Extract deterministic domain facts from one chunk of text.

    Args:
        text: Chunk text to scan.

    Returns:
        Deduplicated extracted facts without document lineage.
    """

    facts: list[ExtractedFact] = []
    facts.extend(_extract_requirements(text))
    facts.extend(_extract_thresholds(text))
    facts.extend(_extract_threshold_table_rows(text))
    facts.extend(_extract_protocols(text))
    facts.extend(_extract_protocol_details(text))
    facts.extend(_extract_sensors(text))
    facts.extend(_extract_devices(text))
    facts.extend(_extract_topics(text))
    return _dedupe_facts(facts)


def extract_facts_from_chunk(chunk: ChunkRecord) -> list[FactRecord]:
    """Extract facts from a chunk and attach source lineage.

    Args:
        chunk: Source chunk whose text should be scanned.

    Returns:
        Fact records with document, version, chunk, system, and status metadata.
    """

    records: list[FactRecord] = []
    for extracted in extract_facts_from_text(chunk.text):
        fact_id = stable_id(
            "fact",
            chunk.document_version_id,
            chunk.chunk_id,
            extracted.fact_key,
            extracted.value,
            extracted.unit,
        )
        records.append(
            FactRecord(
                fact_id=fact_id,
                fact_key=extracted.fact_key,
                fact_type=extracted.fact_type,
                value=extracted.value,
                unit=extracted.unit,
                document_version_id=chunk.document_version_id,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                system_name=chunk.system_name,
                kb_name=chunk.kb_name,
                version=chunk.version,
                status=chunk.status,
                evidence=extracted.evidence,
                requirement_id=extracted.requirement_id,
                semantic_key=extracted.fact_key,
                metadata=dict(extracted.metadata),
            )
        )
    return records


def extract_requirement_ledger_from_chunks(
    chunks: list[ChunkRecord],
) -> tuple[list[RequirementRecord], list[RequirementEvidenceRecord]]:
    """Extract canonical requirements and one-to-many source evidence from chunks.

    Deterministic extraction is the authoritative baseline. Model-based
    enrichment may add annotations later, but it must not invent requirements
    that cannot be linked to one of these evidence spans.
    """

    by_key: dict[str, RequirementRecord] = {}
    evidence_by_id: dict[str, RequirementEvidenceRecord] = {}
    for chunk in chunks:
        for candidate in extract_requirements_from_chunk(chunk):
            requirement_pk = stable_id(
                "requirement",
                chunk.system_name,
                chunk.kb_name,
                chunk.version,
                candidate.canonical_id,
                chunk.document_version_id,
            )
            semantic_key = _ledger_semantic_key(candidate, chunk)
            existing = by_key.get(semantic_key)
            if existing is None:
                by_key[semantic_key] = RequirementRecord(
                    requirement_pk=requirement_pk,
                    canonical_id=candidate.canonical_id,
                    requirement_id=candidate.requirement_id,
                    requirement_type=candidate.requirement_type,
                    category=candidate.category,
                    title=candidate.title,
                    document_version_id=chunk.document_version_id,
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    system_name=chunk.system_name,
                    kb_name=chunk.kb_name,
                    version=chunk.version,
                    status=chunk.status,
                    text=candidate.text,
                    normalized_text=candidate.normalized_text,
                    source_name=chunk.source_name,
                    page=chunk.page,
                    section_title=candidate.section_title or chunk.section_title,
                    story_driving=candidate.story_driving,
                    coverage_required=candidate.coverage_required,
                    extraction_method=candidate.extraction_method,
                    confidence=candidate.confidence,
                    semantic_key=semantic_key,
                    metadata=dict(candidate.metadata),
                )
            else:
                requirement_pk = existing.requirement_pk or requirement_pk
            evidence_id = stable_id(
                "requirement_evidence",
                requirement_pk,
                chunk.chunk_id,
                candidate.start_offset,
                candidate.end_offset,
                candidate.normalized_text,
            )
            evidence_by_id[evidence_id] = RequirementEvidenceRecord(
                requirement_evidence_id=evidence_id,
                requirement_pk=requirement_pk,
                chunk_id=chunk.chunk_id,
                document_version_id=chunk.document_version_id,
                source_name=chunk.source_name,
                page=chunk.page,
                section_title=candidate.section_title or chunk.section_title,
                start_offset=candidate.start_offset,
                end_offset=candidate.end_offset,
                evidence_text=candidate.text,
                extraction_method=candidate.extraction_method,
                confidence=candidate.confidence,
                metadata=dict(candidate.metadata),
            )
    return list(by_key.values()), list(evidence_by_id.values())


def extract_requirements_from_chunk(chunk: ChunkRecord) -> list[ExtractedRequirement]:
    """Extract ledger requirement candidates from one chunk."""

    text = _normalize_pdf_separators(chunk.text)
    candidates: list[ExtractedRequirement] = []
    candidates.extend(_extract_explicit_requirement_records(chunk, text))
    candidates.extend(_extract_nfr_records(chunk, text))
    candidates.extend(_extract_automation_rule_records(chunk, text))
    candidates.extend(_extract_dod_records(chunk, text))
    candidates.extend(_extract_scope_constraint_records(chunk, text))
    return _dedupe_requirements(candidates)


def _extract_requirements(text: str) -> list[ExtractedFact]:
    facts = []
    for match in REQUIREMENT_RE.finditer(text):
        requirement_id = _normalize_requirement_id(match.group(0))
        facts.append(
            ExtractedFact(
                fact_type="requirement",
                fact_key=f"requirement:{requirement_id}",
                value=requirement_id,
                evidence=_evidence_window(text, match.start(), match.end()),
                requirement_id=requirement_id,
                metadata={"start": match.start(), "end": match.end()},
            )
        )
    return facts


def _extract_explicit_requirement_records(
    chunk: ChunkRecord,
    text: str,
) -> list[ExtractedRequirement]:
    records: list[ExtractedRequirement] = []
    matches = list(EXPLICIT_REQUIREMENT_RE.finditer(text))
    for index, match in enumerate(matches):
        requirement_id = _normalize_requirement_id(match.group(0))
        next_start = matches[index + 1].start() if index + 1 < len(matches) else None
        body = _requirement_body_after_match(text, match.end(), next_start)
        if not body:
            continue
        evidence = _clean_evidence(f"{requirement_id} {body}".strip())
        if requirement_id.startswith("AC-"):
            requirement_type = RequirementType.ACCEPTANCE_CRITERION
        elif requirement_id.startswith("BR-"):
            requirement_type = RequirementType.BUSINESS_RULE
        else:
            requirement_type = RequirementType.FUNCTIONAL
        category = _category_from_requirement_id(requirement_id)
        records.append(
            ExtractedRequirement(
                canonical_id=requirement_id,
                requirement_id=requirement_id,
                requirement_type=requirement_type,
                category=category,
                title=_title_from_text(body or evidence),
                text=evidence,
                normalized_text=_normalize_requirement_text(evidence),
                chunk=chunk,
                start_offset=match.start(),
                end_offset=min(next_start or len(text), len(text)),
                section_title=chunk.section_title,
                story_driving=requirement_type
                in {RequirementType.BUSINESS_RULE, RequirementType.FUNCTIONAL},
                coverage_required=requirement_type
                in {RequirementType.BUSINESS_RULE, RequirementType.FUNCTIONAL},
                metadata={"source": "explicit_id", "match": match.group(0)},
            )
        )
    return records


def _extract_nfr_records(chunk: ChunkRecord, text: str) -> list[ExtractedRequirement]:
    section = _section_between(text, "7. Non-Functional Requirements", "8. Acceptance Criteria")
    if not section:
        return []
    flat = _flatten(section)
    area_pattern = "|".join(re.escape(area).replace(r"\ ", r"\s+") for area in NFR_AREAS)
    pattern = re.compile(
        rf"\b(?P<area>{area_pattern})\b\s+(?P<body>.*?)(?=\b(?:{area_pattern})\b|$)",
        re.I,
    )
    records: list[ExtractedRequirement] = []
    for match in pattern.finditer(flat):
        area = _canonical_area(match.group("area"))
        body = _clean_evidence(match.group("body"))
        if not _looks_like_requirement_sentence(body):
            continue
        canonical_id = _generated_requirement_id(
            "NFR",
            area,
            chunk.system_name,
            chunk.kb_name,
            chunk.version,
            body,
        )
        records.append(
            ExtractedRequirement(
                canonical_id=canonical_id,
                requirement_id=canonical_id,
                requirement_type=RequirementType.NON_FUNCTIONAL,
                category=area,
                title=area,
                text=body,
                normalized_text=_normalize_requirement_text(body),
                chunk=chunk,
                start_offset=text.find(match.group("area").split()[0]),
                end_offset=None,
                section_title="Non-Functional Requirements",
                story_driving=True,
                coverage_required=True,
                metadata={"source": "nfr_table", "area": area},
            )
        )
    return records


def _extract_automation_rule_records(chunk: ChunkRecord, text: str) -> list[ExtractedRequirement]:
    section = _section_between(
        text,
        "6.8 Rule-Based Automation",
        "6.9 Sensor and Actuator Data Sheet",
    )
    if not section:
        return []
    lines = _clean_section_lines(section)
    try:
        start = lines.index("Expected Action") + 1
    except ValueError:
        return []
    records: list[ExtractedRequirement] = []
    condition_lines: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if line in AUTOMATION_SAFETY_LEVELS and condition_lines:
            safety_level = line
            index += 1
            action_lines: list[str] = []
            while index < len(lines):
                action_lines.append(lines[index])
                index += 1
                if action_lines[-1].endswith("."):
                    break
            condition = _clean_evidence(" ".join(condition_lines))
            action = _clean_evidence(" ".join(action_lines))
            if condition and action:
                canonical_id = _generated_requirement_id(
                    "AUTO",
                    condition,
                    chunk.system_name,
                    chunk.kb_name,
                    chunk.version,
                    f"{condition} {safety_level} {action}",
                )
                text_value = f"When {condition}, the system shall {action.rstrip('.')}"
                records.append(
                    ExtractedRequirement(
                        canonical_id=canonical_id,
                        requirement_id=canonical_id,
                        requirement_type=RequirementType.AUTOMATION_RULE,
                        category="Rule-Based Automation",
                        title=condition,
                        text=text_value,
                        normalized_text=_normalize_requirement_text(text_value),
                        chunk=chunk,
                        start_offset=text.find(condition_lines[0]),
                        end_offset=None,
                        section_title="Rule-Based Automation",
                        story_driving=True,
                        coverage_required=True,
                        metadata={
                            "source": "automation_table",
                            "condition": condition,
                            "safety_level": safety_level,
                            "expected_action": action,
                        },
                    )
                )
            condition_lines = []
            continue
        condition_lines.append(line)
        index += 1
    return records


def _extract_dod_records(chunk: ChunkRecord, text: str) -> list[ExtractedRequirement]:
    section = _section_after(text, "The feature is complete when:")
    if not section:
        return []
    records: list[ExtractedRequirement] = []
    for line in _clean_section_lines(section):
        if not _looks_like_requirement_sentence(line):
            continue
        canonical_id = _generated_requirement_id(
            "DOD",
            "definition of done",
            chunk.system_name,
            chunk.kb_name,
            chunk.version,
            line,
        )
        records.append(
            ExtractedRequirement(
                canonical_id=canonical_id,
                requirement_id=canonical_id,
                requirement_type=RequirementType.DEFINITION_OF_DONE,
                category="Definition of Done",
                title=_title_from_text(line),
                text=line,
                normalized_text=_normalize_requirement_text(line),
                chunk=chunk,
                start_offset=text.find(line),
                end_offset=None,
                section_title="Definition of Done",
                story_driving=False,
                coverage_required=False,
                metadata={"source": "definition_of_done"},
            )
        )
    return records


def _extract_scope_constraint_records(chunk: ChunkRecord, text: str) -> list[ExtractedRequirement]:
    records: list[ExtractedRequirement] = []
    for heading, next_heading, label in (
        ("3.1 In Scope", "3.2 Out of Scope", "in_scope"),
        ("3.2 Out of Scope", "4. Stakeholders", "out_of_scope"),
    ):
        section = _section_between(text, heading, next_heading)
        if not section:
            continue
        for line in _clean_section_lines(section):
            if not _looks_like_scope_line(line):
                continue
            canonical_id = _generated_requirement_id(
                "SCOPE",
                label,
                chunk.system_name,
                chunk.kb_name,
                chunk.version,
                line,
            )
            records.append(
                ExtractedRequirement(
                    canonical_id=canonical_id,
                    requirement_id=canonical_id,
                    requirement_type=RequirementType.SCOPE_CONSTRAINT,
                    category=label,
                    title=_title_from_text(line),
                    text=line,
                    normalized_text=_normalize_requirement_text(line),
                    chunk=chunk,
                    start_offset=text.find(line),
                    end_offset=None,
                    section_title=heading,
                    story_driving=False,
                    coverage_required=False,
                    metadata={"source": "scope_section", "scope": label},
                )
            )
    return records


def _extract_thresholds(text: str) -> list[ExtractedFact]:
    facts = []
    for pattern in THRESHOLD_PATTERNS:
        for match in pattern.finditer(text):
            sensor = match.group("sensor").lower()
            value = match.group("value")
            unit = _normalize_unit(match.group("unit"))
            facts.append(
                ExtractedFact(
                    fact_type="threshold",
                    fact_key=f"threshold:{sensor}",
                    value=value,
                    unit=unit,
                    evidence=_evidence_window(text, match.start(), match.end()),
                    requirement_id=_nearest_requirement_id(text, match.start()),
                    metadata={"sensor": sensor, "start": match.start(), "end": match.end()},
                )
            )
    return facts


def _extract_threshold_table_rows(text: str) -> list[ExtractedFact]:
    lines = [_clean_line(line) for line in text.splitlines()]
    facts: list[ExtractedFact] = []
    threshold_columns = (
        ("normal_range", "normal range"),
        ("min", "min threshold"),
        ("max", "max threshold"),
        ("critical", "critical level"),
    )
    for index, line in enumerate(lines):
        sensor = _sensor_from_table_label(line)
        if not sensor:
            continue
        values = lines[index + 1 : index + 5]
        if len(values) < 4 or not all(_looks_like_threshold_value(value) for value in values):
            continue
        evidence = " ".join([line, *values])
        position = text.find(line)
        for (kind, label), raw_value in zip(threshold_columns, values, strict=True):
            value, unit = _split_threshold_value(raw_value)
            facts.append(
                ExtractedFact(
                    fact_type="threshold",
                    fact_key=f"threshold:{sensor}:{kind}",
                    value=value,
                    unit=unit,
                    evidence=evidence,
                    requirement_id=_nearest_requirement_id(text, max(position, 0)),
                    metadata={"sensor": sensor, "threshold_kind": kind, "threshold_label": label},
                )
            )
    return facts


def _extract_protocols(text: str) -> list[ExtractedFact]:
    facts = []
    for protocol in PROTOCOLS:
        for match in re.finditer(rf"\b{re.escape(protocol)}\b", text, re.I):
            value = protocol.upper() if protocol in {"MQTT", "CAN", "REST"} else protocol
            facts.append(
                ExtractedFact(
                    fact_type="protocol",
                    fact_key=f"protocol:{value.lower()}",
                    value=value,
                    evidence=_evidence_window(text, match.start(), match.end()),
                    requirement_id=_nearest_requirement_id(text, match.start()),
                    metadata={"start": match.start(), "end": match.end()},
                )
            )
    return facts


def _extract_protocol_details(text: str) -> list[ExtractedFact]:
    facts = []
    for match in REST_ENDPOINT_RE.finditer(text):
        method = match.group("method").upper()
        path = match.group("path")
        facts.append(
            ExtractedFact(
                fact_type="protocol_detail",
                fact_key=f"protocol_detail:rest:{method.lower()}:{path.lower()}",
                value=f"{method} {path}",
                evidence=_evidence_window(text, match.start(), match.end()),
                requirement_id=_nearest_requirement_id(text, match.start()),
                metadata={"protocol": "REST", "method": method, "path": path},
            )
        )
    for match in CAN_ID_RE.finditer(text):
        can_id = match.group("can_id")
        facts.append(
            ExtractedFact(
                fact_type="protocol_detail",
                fact_key=f"protocol_detail:can:{can_id.lower()}",
                value=can_id,
                evidence=_evidence_window(text, match.start(), match.end()),
                requirement_id=_nearest_requirement_id(text, match.start()),
                metadata={"protocol": "CAN", "can_id": can_id},
            )
        )
    for match in MODBUS_REGISTER_RE.finditer(text):
        kind = match.group("kind").lower()
        address = match.group("address")
        facts.append(
            ExtractedFact(
                fact_type="protocol_detail",
                fact_key=f"protocol_detail:modbus:{kind}:{address}",
                value=f"{kind} {address}",
                evidence=_evidence_window(text, match.start(), match.end()),
                requirement_id=_nearest_requirement_id(text, match.start()),
                metadata={"protocol": "Modbus", "kind": kind, "address": address},
            )
        )
    return facts


def _extract_sensors(text: str) -> list[ExtractedFact]:
    facts = []
    for sensor in SENSORS:
        for match in re.finditer(rf"\b{sensor}\b", text, re.I):
            normalized = sensor.lower()
            facts.append(
                ExtractedFact(
                    fact_type="sensor",
                    fact_key=f"sensor:{normalized}",
                    value=normalized,
                    evidence=_evidence_window(text, match.start(), match.end()),
                    requirement_id=_nearest_requirement_id(text, match.start()),
                    metadata={"start": match.start(), "end": match.end()},
                )
            )
    return facts


def _extract_devices(text: str) -> list[ExtractedFact]:
    facts = []
    for match in DEVICE_RE.finditer(text):
        name = match.group("name").strip(".,;:")
        facts.append(
            ExtractedFact(
                fact_type="device",
                fact_key=f"device:{name.lower()}",
                value=name,
                evidence=_evidence_window(text, match.start(), match.end()),
                requirement_id=_nearest_requirement_id(text, match.start()),
                metadata={"start": match.start(), "end": match.end()},
            )
        )
    return facts


def _extract_topics(text: str) -> list[ExtractedFact]:
    facts = []
    for match in MQTT_TOPIC_RE.finditer(text):
        topic = match.group("topic").strip(".,;:")
        facts.append(
            ExtractedFact(
                fact_type="topic",
                fact_key=f"topic:mqtt:{topic.lower()}",
                value=topic,
                evidence=_evidence_window(text, match.start(), match.end()),
                requirement_id=_nearest_requirement_id(text, match.start()),
                metadata={"protocol": "MQTT", "topic": topic},
            )
        )
    return facts


def _clean_line(line: str) -> str:
    return " ".join(line.split()).strip()


def _sensor_from_table_label(line: str) -> str | None:
    match = re.fullmatch(rf"(?P<sensor>{SENSOR_RE})\s+Sensor", line, flags=re.I)
    return match.group("sensor").lower() if match else None


def _looks_like_threshold_value(value: str) -> bool:
    return bool(
        re.fullmatch(
            rf"(?:[<>]=?\s*)?-?\d+(?:\.\d+)?(?:\s*-\s*-?\d+(?:\.\d+)?)?\s*(?:°?\s*{UNIT_RE})?",
            value,
            flags=re.I,
        )
    )


def _split_threshold_value(raw_value: str) -> tuple[str, str | None]:
    text = raw_value.replace("°", "").strip()
    match = re.fullmatch(
        rf"(?P<value>(?:[<>]=?\s*)?-?\d+(?:\.\d+)?(?:\s*-\s*-?\d+(?:\.\d+)?)?)\s*"
        rf"(?P<unit>{UNIT_RE})?",
        text,
        flags=re.I,
    )
    if not match:
        return text, None
    value = re.sub(r"\s+", "", match.group("value"))
    return value, _normalize_unit(match.group("unit"))


def _evidence_window(text: str, start: int, end: int, radius: int = 120) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return " ".join(text[left:right].split())


def _normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    normalized = unit.strip()
    if normalized.lower() == "deg c":
        return "C"
    if normalized.lower() == "percent":
        return "%"
    return normalized


def _nearest_requirement_id(text: str, position: int) -> str | None:
    nearest: str | None = None
    for match in REQUIREMENT_RE.finditer(text):
        if match.start() > position:
            break
        nearest = _normalize_requirement_id(match.group(0))
    return nearest


def _normalize_requirement_id(value: str) -> str:
    normalized = _normalize_pdf_separators(value).upper()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    br_match = re.fullmatch(
        r"BR\s*[-_ ]?\s*(?P<area>[A-Z]{2,10})\s*[-_ ]?\s*(?P<num>\d+(?:\.\d+)?)",
        normalized,
    )
    if br_match:
        return f"BR-{br_match.group('area')}-{br_match.group('num').zfill(3)}"
    simple_match = re.fullmatch(
        r"(?P<prefix>REQ|BRD|SRS|FRS|API|UC|AC)\s*[-_ ]?\s*(?P<num>\d+(?:\.\d+)?)",
        normalized,
    )
    if simple_match:
        return f"{simple_match.group('prefix')}-{simple_match.group('num').zfill(3)}"
    return re.sub(r"\s*[-_]\s*", "-", normalized)


def _normalize_pdf_separators(text: str) -> str:
    return (
        text.replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2015", "-")
    )


def _requirement_body_after_match(text: str, start: int, next_start: int | None) -> str:
    end = next_start if next_start is not None else len(text)
    raw = text[start:end]
    raw = re.split(
        r"\n\s*(?:SIIMCS_BRD_V\d+\.md|\d{4}-\d{2}-\d{2}|\d+\s*/\s*\d+)\s*$",
        raw,
        maxsplit=1,
        flags=re.I,
    )[0]
    lines = _clean_section_lines(raw)
    filtered: list[str] = []
    for line in lines:
        if line in {"ID", "Requirement", "Acceptance Criteria"}:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)*\s+.+", line) and filtered:
            break
        filtered.append(line)
        if line.endswith("."):
            break
    return _clean_evidence(" ".join(filtered))


def _category_from_requirement_id(requirement_id: str) -> str:
    if requirement_id.startswith("BR-"):
        parts = requirement_id.split("-")
        if len(parts) >= 3:
            return parts[1]
    if requirement_id.startswith("AC-"):
        return "Acceptance Criteria"
    return requirement_id.split("-", 1)[0]


def _title_from_text(text: str, *, max_words: int = 9) -> str:
    words = _clean_evidence(text).rstrip(".").split()
    return " ".join(words[:max_words]) if words else "Requirement"


def _normalize_requirement_text(text: str) -> str:
    return re.sub(r"\s+", " ", _normalize_pdf_separators(text)).strip().lower()


def _clean_evidence(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" -;\t")


def _flatten(text: str) -> str:
    return _clean_evidence(EXHAUSTIVE_SECTION_FOOTER_RE.sub(" ", text))


def _canonical_area(value: str) -> str:
    normalized = _clean_evidence(value).lower()
    for area in NFR_AREAS:
        if normalized == area.lower():
            return area
    if normalized == "embedded safety":
        return "Embedded Safety"
    return normalized.title()


def _section_between(text: str, start_marker: str, end_marker: str) -> str:
    normalized = _normalize_pdf_separators(text)
    start = normalized.lower().find(start_marker.lower())
    if start < 0:
        return ""
    start += len(start_marker)
    end = normalized.lower().find(end_marker.lower(), start)
    if end < 0:
        end = len(normalized)
    return normalized[start:end]


def _section_after(text: str, start_marker: str) -> str:
    normalized = _normalize_pdf_separators(text)
    start = normalized.lower().find(start_marker.lower())
    if start < 0:
        return ""
    return normalized[start + len(start_marker) :]


def _clean_section_lines(section: str) -> list[str]:
    lines: list[str] = []
    for raw_line in section.splitlines():
        line = _clean_evidence(EXHAUSTIVE_SECTION_FOOTER_RE.sub(" ", raw_line))
        if not line:
            continue
        if line in {"ID", "Requirement", "Area", "Condition", "Safety", "Level"}:
            continue
        lines.append(line)
    return lines


def _looks_like_requirement_sentence(text: str) -> bool:
    lowered = text.lower()
    if len(text.split()) < 4:
        return False
    return any(
        marker in lowered
        for marker in (
            "shall",
            "must",
            "should",
            "support",
            "configured",
            "verified",
            "approve",
            "acceptance",
            "approved",
            "monitored",
            "available",
            "working",
            "tested",
        )
    )


def _looks_like_scope_line(text: str) -> bool:
    if len(text.split()) < 3:
        return False
    return not text.endswith(":") and not re.fullmatch(r"\d+(?:\.\d+)*.*", text)


def _generated_requirement_id(
    prefix: str,
    category: str,
    system_name: str,
    kb_name: str,
    version: str,
    normalized_source: str,
) -> str:
    slug = re.sub(r"[^A-Z0-9]+", "-", category.upper()).strip("-")
    slug = "-".join(part for part in slug.split("-") if part)[:40] or "ITEM"
    suffix = stable_id(
        "requirement_id",
        system_name,
        kb_name,
        version,
        prefix,
        category,
        _normalize_requirement_text(normalized_source),
    )[-8:].upper()
    if prefix == "DOD":
        return f"DOD-{suffix}"
    return f"{prefix}-{slug}-{suffix}"


def _ledger_semantic_key(candidate: ExtractedRequirement, chunk: ChunkRecord) -> str:
    if candidate.metadata.get("source") == "explicit_id":
        return stable_id(
            "requirement_semantic_key",
            chunk.system_name,
            chunk.kb_name,
            chunk.version,
            candidate.requirement_type.value,
            candidate.canonical_id,
        )
    return stable_id(
        "requirement_semantic_key",
        chunk.system_name,
        chunk.kb_name,
        chunk.version,
        candidate.requirement_type.value,
        candidate.canonical_id,
        candidate.normalized_text,
    )


def _dedupe_requirements(records: list[ExtractedRequirement]) -> list[ExtractedRequirement]:
    deduped: dict[tuple[str, str, str], ExtractedRequirement] = {}
    for record in records:
        key = (
            record.requirement_type.value,
            record.canonical_id,
            record.normalized_text,
        )
        deduped.setdefault(key, record)
    return list(deduped.values())


def _dedupe_facts(facts: list[ExtractedFact]) -> list[ExtractedFact]:
    seen: set[tuple[str, str, str | None]] = set()
    deduped: list[ExtractedFact] = []
    for fact in facts:
        key = (fact.fact_key, fact.value, fact.unit)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fact)
    return deduped
