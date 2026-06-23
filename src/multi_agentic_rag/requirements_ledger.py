"""Requirement ledger query classification, rendering, and artifacts."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from multi_agentic_rag.domain import (
    RequirementCoverageRecord,
    RequirementCoverageStatus,
    RequirementEvidenceRecord,
    RequirementRecord,
)
from multi_agentic_rag.utils.hashing import stable_id


class RequirementQueryIntent(StrEnum):
    """Deterministic query kind for answer routing."""

    EXHAUSTIVE_REQUIREMENT_QUERY = "exhaustive_requirement_query"
    SEMANTIC_QA_QUERY = "semantic_qa_query"
    THRESHOLD_QUERY = "threshold_query"


EXHAUSTIVE_REQUIREMENT_PATTERNS = (
    "all requirements",
    "every requirement",
    "complete requirements",
    "entire requirement list",
    "summarize all requirements",
    "list all business rules",
    "all business rules",
    "requirements coverage",
    "full traceability",
)


def classify_requirement_query(question: str) -> RequirementQueryIntent:
    """Classify whether a question must enumerate the exact ledger."""

    normalized = re.sub(r"\s+", " ", question.strip().lower())
    if any(pattern in normalized for pattern in EXHAUSTIVE_REQUIREMENT_PATTERNS):
        return RequirementQueryIntent.EXHAUSTIVE_REQUIREMENT_QUERY
    if "threshold" in normalized or "limit" in normalized or "setpoint" in normalized:
        return RequirementQueryIntent.THRESHOLD_QUERY
    return RequirementQueryIntent.SEMANTIC_QA_QUERY


def requirement_inventory_payload(
    requirements: list[RequirementRecord],
    evidence: list[RequirementEvidenceRecord],
    *,
    system_name: str,
    kb_name: str,
    version: str,
) -> dict[str, Any]:
    """Build a JSON-serializable inventory with evidence grouped by requirement."""

    evidence_by_pk: dict[str, list[RequirementEvidenceRecord]] = defaultdict(list)
    for item in evidence:
        evidence_by_pk[item.requirement_pk].append(item)
    counts = Counter(requirement.requirement_type.value for requirement in requirements)
    return {
        "system": system_name,
        "knowledge_base": kb_name,
        "version": version,
        "generated_at": datetime.now(UTC).isoformat(),
        "total_ledger_records": len(requirements),
        "counts_by_type": dict(sorted(counts.items())),
        "requirements": [
            _requirement_payload(
                requirement,
                evidence_by_pk.get(requirement.requirement_pk or "", []),
            )
            for requirement in requirements
        ],
    }


def render_requirement_inventory_markdown(payload: dict[str, Any]) -> str:
    """Render a complete requirement inventory as Markdown."""

    lines = [
        f"# Requirement Inventory: {payload['system']} {payload['version']}",
        "",
        f"- Knowledge base: {payload['knowledge_base']}",
        f"- Total ledger records: {payload['total_ledger_records']}",
        "",
        "## Counts",
        "",
    ]
    for requirement_type, count in payload["counts_by_type"].items():
        lines.append(f"- {requirement_type}: {count}")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for requirement in payload["requirements"]:
        grouped[requirement["requirement_type"]].append(requirement)
    for requirement_type in sorted(grouped):
        lines.extend(["", f"## {requirement_type.replace('_', ' ').title()}", ""])
        current_category: str | None = None
        for item in grouped[requirement_type]:
            category = item.get("category") or "Uncategorized"
            if category != current_category:
                lines.extend(["", f"### {category}", ""])
                current_category = category
            evidence_refs = ", ".join(
                f"p.{ev['page']} `{ev['chunk_id']}`" for ev in item.get("evidence", [])
            )
            lines.append(
                f"- **{item['canonical_id']}**: {item['text']} "
                f"_(evidence: {evidence_refs or 'missing'})_"
            )
    lines.append("")
    return "\n".join(lines)


def render_requirement_answer(payload: dict[str, Any], artifact_paths: list[Path]) -> str:
    """Render the CLI answer for an exhaustive requirement question."""

    counts = ", ".join(
        f"{name}={count}" for name, count in payload["counts_by_type"].items()
    )
    lines = [
        "Requirement ledger enumeration:",
        f"- total records: {payload['total_ledger_records']}",
        f"- counts: {counts}",
        "",
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for requirement in payload["requirements"]:
        grouped[requirement["requirement_type"]].append(requirement)
    for requirement_type in sorted(grouped):
        lines.append(f"{requirement_type.replace('_', ' ').title()}:")
        for item in grouped[requirement_type]:
            evidence = item.get("evidence", [])
            refs = ", ".join(f"p.{ev['page']} {ev['chunk_id']}" for ev in evidence[:2])
            suffix = f" [{refs}]" if refs else " [missing evidence]"
            lines.append(f"- {item['canonical_id']}: {item['text']}{suffix}")
        lines.append("")
    if artifact_paths:
        lines.append("Artifacts:")
        for path in artifact_paths:
            lines.append(f"- {path}")
    return "\n".join(lines).strip()


def write_requirement_inventory_artifacts(
    *,
    output_dir: Path,
    payload: dict[str, Any],
    stem: str = "requirements_inventory",
) -> list[Path]:
    """Write JSON and Markdown requirement inventory artifacts."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(render_requirement_inventory_markdown(payload), encoding="utf-8")
    return [json_path, markdown_path]


def build_coverage_records(
    *,
    requirements: list[RequirementRecord],
    story_requirement_ids: dict[str, list[str]],
) -> list[RequirementCoverageRecord]:
    """Build deterministic coverage records from story-to-requirement IDs."""

    story_by_requirement: dict[str, list[str]] = defaultdict(list)
    for story_id, requirement_ids in story_requirement_ids.items():
        for requirement_id in requirement_ids:
            story_by_requirement[requirement_id].append(story_id)
    records: list[RequirementCoverageRecord] = []
    for requirement in requirements:
        canonical_id = requirement.canonical_id or requirement.requirement_id
        story_ids = sorted(
            {
                *story_by_requirement.get(canonical_id, []),
                *story_by_requirement.get(requirement.requirement_id, []),
            }
        )
        status = (
            RequirementCoverageStatus.COVERED
            if story_ids
            else RequirementCoverageStatus.NOT_APPLICABLE
            if not requirement.coverage_required
            else RequirementCoverageStatus.MISSING
        )
        coverage_story_ids: list[str | None] = [*story_ids] if story_ids else [None]
        for coverage_story_id in coverage_story_ids:
            records.append(
                RequirementCoverageRecord(
                    coverage_id=stable_id(
                        "requirement_coverage",
                        requirement.requirement_pk,
                        coverage_story_id or "unassigned",
                    ),
                    requirement_pk=requirement.requirement_pk or "",
                    canonical_id=canonical_id,
                    story_id=coverage_story_id,
                    coverage_status=status,
                    validation_status=(
                        "passed"
                        if status != RequirementCoverageStatus.MISSING
                        else "failed"
                    ),
                    source_chunk_ids=[requirement.chunk_id],
                    source_pages=[requirement.page] if requirement.page else [],
                )
            )
    return records


def coverage_payload(
    *,
    requirements: list[RequirementRecord],
    coverage: list[RequirementCoverageRecord],
) -> dict[str, Any]:
    """Build a deterministic coverage matrix payload."""

    by_requirement: dict[str, list[RequirementCoverageRecord]] = defaultdict(list)
    for record in coverage:
        by_requirement[record.requirement_pk].append(record)
    rows = []
    for requirement in requirements:
        records = by_requirement.get(requirement.requirement_pk or "", [])
        story_ids = sorted({record.story_id for record in records if record.story_id})
        status = _aggregate_coverage_status(records, requirement.coverage_required)
        rows.append(
            {
                "requirement_pk": requirement.requirement_pk,
                "canonical_id": requirement.canonical_id or requirement.requirement_id,
                "requirement_type": requirement.requirement_type.value,
                "category": requirement.category,
                "coverage_required": requirement.coverage_required,
                "story_ids": story_ids,
                "coverage_status": status.value,
                "deferred_reason": next(
                    (record.deferred_reason for record in records if record.deferred_reason),
                    None,
                ),
                "source_chunk_ids": sorted({requirement.chunk_id}),
                "source_pages": [requirement.page] if requirement.page else [],
                "validation_status": (
                    "passed" if status != RequirementCoverageStatus.MISSING else "failed"
                ),
            }
        )
    counts = Counter(row["coverage_status"] for row in rows)
    return {"rows": rows, "counts": dict(sorted(counts.items()))}


def write_coverage_artifacts(
    *,
    output_dir: Path,
    payload: dict[str, Any],
) -> list[Path]:
    """Write JSON and CSV coverage matrix artifacts."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "requirement_story_coverage.json"
    csv_path = output_dir / "requirement_story_coverage.csv"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    fieldnames = [
        "requirement_pk",
        "canonical_id",
        "requirement_type",
        "category",
        "coverage_required",
        "story_ids",
        "coverage_status",
        "deferred_reason",
        "source_chunk_ids",
        "source_pages",
        "validation_status",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in payload["rows"]:
            writer.writerow(
                {
                    **row,
                    "story_ids": ";".join(row["story_ids"]),
                    "source_chunk_ids": ";".join(row["source_chunk_ids"]),
                    "source_pages": ";".join(str(page) for page in row["source_pages"]),
                }
            )
    return [json_path, csv_path]


def _requirement_payload(
    requirement: RequirementRecord,
    evidence: list[RequirementEvidenceRecord],
) -> dict[str, Any]:
    return {
        "requirement_pk": requirement.requirement_pk,
        "canonical_id": requirement.canonical_id or requirement.requirement_id,
        "requirement_id": requirement.requirement_id,
        "requirement_type": requirement.requirement_type.value,
        "category": requirement.category,
        "title": requirement.title,
        "text": requirement.text,
        "normalized_text": requirement.normalized_text,
        "system_name": requirement.system_name,
        "kb_name": requirement.kb_name,
        "document_id": requirement.document_id,
        "document_version_id": requirement.document_version_id,
        "version": requirement.version,
        "status": requirement.status.value,
        "source_name": requirement.source_name,
        "page": requirement.page,
        "section_title": requirement.section_title,
        "story_driving": requirement.story_driving,
        "coverage_required": requirement.coverage_required,
        "extraction_method": requirement.extraction_method,
        "confidence": requirement.confidence,
        "semantic_key": requirement.semantic_key,
        "metadata": requirement.metadata,
        "evidence": [
            {
                "requirement_evidence_id": item.requirement_evidence_id,
                "chunk_id": item.chunk_id,
                "document_version_id": item.document_version_id,
                "source_name": item.source_name,
                "page": item.page,
                "section_title": item.section_title,
                "start_offset": item.start_offset,
                "end_offset": item.end_offset,
                "evidence_text": item.evidence_text,
                "extraction_method": item.extraction_method,
                "confidence": item.confidence,
                "metadata": item.metadata,
            }
            for item in evidence
        ],
    }


def _aggregate_coverage_status(
    records: list[RequirementCoverageRecord],
    coverage_required: bool,
) -> RequirementCoverageStatus:
    if any(record.coverage_status == RequirementCoverageStatus.COVERED for record in records):
        return RequirementCoverageStatus.COVERED
    if any(
        record.coverage_status == RequirementCoverageStatus.PARTIALLY_COVERED
        for record in records
    ):
        return RequirementCoverageStatus.PARTIALLY_COVERED
    if any(record.coverage_status == RequirementCoverageStatus.DEFERRED for record in records):
        return RequirementCoverageStatus.DEFERRED
    if not coverage_required:
        return RequirementCoverageStatus.NOT_APPLICABLE
    return RequirementCoverageStatus.MISSING
