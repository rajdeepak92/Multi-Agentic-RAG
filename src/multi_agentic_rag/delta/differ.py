"""Deterministic fact-level delta computation."""

from __future__ import annotations

from multi_agentic_rag.delta.classifier import classify_change_magnitude, classify_risk
from multi_agentic_rag.models import DeltaRecord, FactRecord
from multi_agentic_rag.utils.hashing import stable_id


def compute_fact_deltas(
    *,
    system_name: str,
    from_version: str,
    to_version: str,
    old_facts: list[FactRecord],
    new_facts: list[FactRecord],
) -> list[DeltaRecord]:
    """Compare old and new facts by stable fact keys."""

    old_by_key = _latest_by_key(old_facts)
    new_by_key = _latest_by_key(new_facts)
    deltas: list[DeltaRecord] = []
    for fact_key in sorted(set(old_by_key) | set(new_by_key)):
        old_fact = old_by_key.get(fact_key)
        new_fact = new_by_key.get(fact_key)
        if old_fact and new_fact and _same_fact_value(old_fact, new_fact):
            continue
        if old_fact and new_fact:
            change_type = "modified"
            old_value = _value_with_unit(old_fact)
            new_value = _value_with_unit(new_fact)
            requirement_id = new_fact.requirement_id or old_fact.requirement_id
            evidence = [old_fact.evidence, new_fact.evidence]
        elif old_fact:
            change_type = "removed"
            old_value = _value_with_unit(old_fact)
            new_value = None
            requirement_id = old_fact.requirement_id
            evidence = [old_fact.evidence]
        else:
            change_type = "added"
            old_value = None
            new_value = _value_with_unit(new_fact) if new_fact else None
            requirement_id = new_fact.requirement_id if new_fact else None
            evidence = [new_fact.evidence] if new_fact else []

        magnitude = classify_change_magnitude(
            old_fact.value if old_fact else None,
            new_fact.value if new_fact else None,
        )
        risk = classify_risk(change_type, magnitude, fact_key)
        deltas.append(
            DeltaRecord(
                delta_id=stable_id(
                    "delta",
                    system_name,
                    from_version,
                    to_version,
                    fact_key,
                    old_value,
                    new_value,
                ),
                system_name=system_name,
                from_version=from_version,
                to_version=to_version,
                fact_key=fact_key,
                change_type=change_type,
                change_magnitude=magnitude,
                old_value=old_value,
                new_value=new_value,
                affected_requirement_id=requirement_id,
                risk_level=risk,
                evidence=evidence,
            )
        )
    return deltas


def _latest_by_key(facts: list[FactRecord]) -> dict[str, FactRecord]:
    return {fact.semantic_key or fact.fact_key: fact for fact in facts}


def _same_fact_value(old_fact: FactRecord, new_fact: FactRecord) -> bool:
    return old_fact.value == new_fact.value and old_fact.unit == new_fact.unit


def _value_with_unit(fact: FactRecord) -> str:
    return f"{fact.value} {fact.unit}".strip() if fact.unit else fact.value
