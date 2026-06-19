"""Deterministic rule-based extractors for engineering GraphRAG evidence."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from multi_agentic_rag.domain import ChunkRecord, FactRecord
from multi_agentic_rag.utils.hashing import stable_id

REQUIREMENT_RE = re.compile(
    r"\b(?:(?:REQ|BRD|SRS|FRS|API|UC)[-_]?\d+(?:\.\d+)?|"
    r"BR[-_]\s*[A-Z]{2,10}[-_]\s*\d+(?:\.\d+)?)\b",
    re.I,
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
    return re.sub(r"\s*[-_]\s*", "-", value.upper())


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
