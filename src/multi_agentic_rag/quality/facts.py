"""Deterministic fact validation and golden-dataset quality measurement."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

from multi_agentic_rag.domain import FactRecord

_NUMBER_RE = re.compile(r"(?P<operator>>=|<=|>|<)?\s*(?P<number>-?\d+(?:\.\d+)?)")
_RANGE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*[-–]\s*(-?\d+(?:\.\d+)?)")


class FactValidationFinding(BaseModel):
    """One deterministic fact-quality finding."""

    fact_id: str
    check: str
    status: str
    message: str


class FactQualitySummary(BaseModel):
    """Aggregate fact-quality report."""

    fact_count: int
    passed_count: int
    failed_count: int
    duplicate_count: int
    contradiction_count: int
    missing_evidence_count: int
    numeric_error_count: int
    unit_error_count: int
    findings: list[FactValidationFinding] = Field(default_factory=list)


def validate_facts(facts: list[FactRecord]) -> FactQualitySummary:
    """Validate authoritative facts without using an LLM."""

    findings: list[FactValidationFinding] = []
    findings.extend(_validate_individual_facts(facts))
    findings.extend(_duplicate_findings(facts))
    findings.extend(_contradiction_findings(facts))
    failed_ids = {finding.fact_id for finding in findings if finding.status == "failed"}
    return FactQualitySummary(
        fact_count=len(facts),
        passed_count=len(facts) - len(failed_ids),
        failed_count=len(failed_ids),
        duplicate_count=sum(1 for item in findings if item.check == "duplicate_detection"),
        contradiction_count=sum(
            1 for item in findings if item.check == "contradiction_detection"
        ),
        missing_evidence_count=sum(
            1 for item in findings if item.check == "exact_evidence_containment"
        ),
        numeric_error_count=sum(1 for item in findings if item.check == "numeric_parsing"),
        unit_error_count=sum(1 for item in findings if item.check == "unit_validation"),
        findings=findings,
    )


def evaluate_fact_quality(
    facts: list[FactRecord],
    golden_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate extracted facts against labelled golden records."""

    predicted_keys = {_fact_match_key(fact) for fact in facts}
    golden_keys = {
        _golden_match_key(record)
        for record in golden_records
        if _golden_match_key(record)
    }
    true_positive = len(predicted_keys & golden_keys)
    false_positive = len(predicted_keys - golden_keys)
    false_negative = len(golden_keys - predicted_keys)
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    validation = validate_facts(facts)
    return {
        "fact_count": len(facts),
        "golden_count": len(golden_keys),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "validation": validation.model_dump(mode="json"),
        "missing_golden_keys": sorted(golden_keys - predicted_keys),
        "unsupported_predicted_keys": sorted(predicted_keys - golden_keys),
    }


def render_fact_quality_markdown(report: dict[str, Any]) -> str:
    """Render a concise Markdown fact-quality report."""

    validation = report.get("validation", {})
    lines = [
        "# Fact Quality Report",
        "",
        f"- Fact count: {report.get('fact_count', validation.get('fact_count', 0))}",
        f"- Golden count: {report.get('golden_count', 'not supplied')}",
        f"- Precision: {_metric(report.get('precision'))}",
        f"- Recall: {_metric(report.get('recall'))}",
        f"- F1: {_metric(report.get('f1'))}",
        f"- Failed facts: {validation.get('failed_count', 0)}",
        f"- Duplicates: {validation.get('duplicate_count', 0)}",
        f"- Contradictions: {validation.get('contradiction_count', 0)}",
        f"- Numeric errors: {validation.get('numeric_error_count', 0)}",
        f"- Unit errors: {validation.get('unit_error_count', 0)}",
    ]
    findings = validation.get("findings", [])
    if findings:
        lines.extend(["", "## Findings"])
        for finding in findings[:50]:
            lines.append(
                "- "
                f"{finding['fact_id']} [{finding['check']}]: {finding['message']}"
            )
    return "\n".join(lines) + "\n"


def _validate_individual_facts(facts: list[FactRecord]) -> list[FactValidationFinding]:
    findings: list[FactValidationFinding] = []
    for fact in facts:
        evidence = fact.evidence or ""
        if not evidence.strip() or not _contains_value(evidence, fact.value):
            findings.append(
                FactValidationFinding(
                    fact_id=fact.fact_id,
                    check="exact_evidence_containment",
                    status="failed",
                    message="Fact value is not contained in exact source evidence.",
                )
            )
        if _looks_numeric(fact) and not _valid_numeric_fact(fact):
            findings.append(
                FactValidationFinding(
                    fact_id=fact.fact_id,
                    check="numeric_parsing",
                    status="failed",
                    message="Numeric fact value could not be parsed or range order is invalid.",
                )
            )
        if fact.unit and fact.unit not in evidence:
            findings.append(
                FactValidationFinding(
                    fact_id=fact.fact_id,
                    check="unit_validation",
                    status="failed",
                    message="Fact unit is not present in exact source evidence.",
                )
            )
    return findings


def _duplicate_findings(facts: list[FactRecord]) -> list[FactValidationFinding]:
    groups: dict[tuple[str, str, str | None, str], list[FactRecord]] = defaultdict(list)
    for fact in facts:
        groups[(fact.fact_key, fact.value, fact.unit, fact.document_version_id)].append(fact)
    findings: list[FactValidationFinding] = []
    for group in groups.values():
        if len(group) <= 1:
            continue
        for fact in group[1:]:
            findings.append(
                FactValidationFinding(
                    fact_id=fact.fact_id,
                    check="duplicate_detection",
                    status="failed",
                    message="Duplicate fact key/value/unit in the same document version.",
                )
            )
    return findings


def _contradiction_findings(facts: list[FactRecord]) -> list[FactValidationFinding]:
    groups: dict[tuple[str, str], set[tuple[str, str | None]]] = defaultdict(set)
    by_key: dict[tuple[str, str], list[FactRecord]] = defaultdict(list)
    for fact in facts:
        key = (fact.fact_key, fact.document_version_id)
        groups[key].add((fact.value, fact.unit))
        by_key[key].append(fact)
    findings: list[FactValidationFinding] = []
    for key, values in groups.items():
        if len(values) <= 1:
            continue
        for fact in by_key[key]:
            findings.append(
                FactValidationFinding(
                    fact_id=fact.fact_id,
                    check="contradiction_detection",
                    status="failed",
                    message="Same fact key has conflicting values in one document version.",
                )
            )
    return findings


def _contains_value(evidence: str, value: str) -> bool:
    compact_evidence = re.sub(r"\s+", "", evidence.lower())
    compact_value = re.sub(r"\s+", "", value.lower())
    return compact_value in compact_evidence


def _looks_numeric(fact: FactRecord) -> bool:
    return bool(_NUMBER_RE.search(fact.value)) or fact.fact_type in {
        "threshold",
        "range",
        "critical_value",
        "polling_count",
        "polling_interval",
        "retention_period",
    }


def _valid_numeric_fact(fact: FactRecord) -> bool:
    range_match = _RANGE_RE.search(fact.value)
    if range_match:
        minimum = float(range_match.group(1))
        maximum = float(range_match.group(2))
        return minimum <= maximum
    return bool(_NUMBER_RE.search(fact.value))


def _fact_match_key(fact: FactRecord) -> str:
    return "|".join(
        [
            fact.fact_key.strip().lower(),
            re.sub(r"\s+", "", fact.value.lower()),
            (fact.unit or "").strip().lower(),
        ]
    )


def _golden_match_key(record: dict[str, Any]) -> str:
    fact_key = str(record.get("fact_key") or record.get("expected_fact_key") or "")
    value = str(record.get("value") or record.get("expected_value") or "")
    unit = str(record.get("unit") or "")
    if not fact_key or not value:
        return ""
    return "|".join(
        [
            fact_key.strip().lower(),
            re.sub(r"\s+", "", value.lower()),
            unit.strip().lower(),
        ]
    )


def _metric(value: Any) -> str:
    if isinstance(value, int | float):
        return f"{float(value):.3f}"
    return "not calculated"
