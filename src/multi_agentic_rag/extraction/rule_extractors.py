"""Deterministic rule-based extractors for Phase 1."""

from __future__ import annotations

import re

from multi_agentic_rag.extraction.schemas import ExtractedFact
from multi_agentic_rag.models import ChunkRecord, FactRecord
from multi_agentic_rag.utils.hashing import stable_id

REQUIREMENT_RE = re.compile(r"\b(?:REQ|BRD|SRS|FRS|API|UC|TEST)[-_]?\d+(?:\.\d+)?\b", re.I)
PROTOCOLS = ("Modbus", "MQTT", "CAN", "REST")
SENSORS = ("temperature", "pressure", "vibration")
UNIT_RE = r"(?:deg\s*C|°C|C|F|K|bar|psi|Pa|kPa|MPa|%|percent|rpm|Hz|ms|s|seconds?)"
THRESHOLD_PATTERNS = [
    re.compile(
        rf"\b(?P<sensor>temperature|pressure|vibration)\b.{{0,80}}?"
        rf"\b(?:threshold|limit|setpoint|must not exceed|shall not exceed|maximum|max|min)\b"
        rf".{{0,40}}?(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>{UNIT_RE})?\b",
        re.I,
    ),
    re.compile(
        rf"\b(?:threshold|limit|setpoint|must not exceed|shall not exceed|maximum|max|min)\b"
        rf".{{0,80}}?\b(?P<sensor>temperature|pressure|vibration)\b"
        rf".{{0,40}}?(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>{UNIT_RE})?\b",
        re.I,
    ),
]


def extract_facts_from_text(text: str) -> list[ExtractedFact]:
    """Extract requirements, thresholds, protocols, and known sensor names."""

    facts: list[ExtractedFact] = []
    facts.extend(_extract_requirements(text))
    facts.extend(_extract_thresholds(text))
    facts.extend(_extract_protocols(text))
    facts.extend(_extract_sensors(text))
    return _dedupe_facts(facts)


def extract_facts_from_chunk(chunk: ChunkRecord) -> list[FactRecord]:
    """Extract facts from a chunk and attach source lineage."""

    records: list[FactRecord] = []
    for extracted in extract_facts_from_text(chunk.text):
        fact_id = stable_id(
            "fact",
            chunk.document_id,
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
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                system_name=chunk.system_name,
                version=chunk.version,
                status=chunk.status,
                evidence=extracted.evidence,
                requirement_id=extracted.requirement_id,
                metadata=extracted.metadata,
            )
        )
    return records


def _extract_requirements(text: str) -> list[ExtractedFact]:
    facts = []
    for match in REQUIREMENT_RE.finditer(text):
        requirement_id = match.group(0).upper().replace("_", "-")
        evidence = _evidence_window(text, match.start(), match.end())
        facts.append(
            ExtractedFact(
                fact_type="requirement",
                fact_key=f"requirement:{requirement_id}",
                value=requirement_id,
                evidence=evidence,
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
            evidence = _evidence_window(text, match.start(), match.end())
            facts.append(
                ExtractedFact(
                    fact_type="threshold",
                    fact_key=f"threshold:{sensor}",
                    value=value,
                    unit=unit,
                    evidence=evidence,
                    metadata={
                        "sensor": sensor,
                        "start": match.start(),
                        "end": match.end(),
                    },
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
                    metadata={"start": match.start(), "end": match.end()},
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
                    metadata={"start": match.start(), "end": match.end()},
                )
            )
    return facts


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
