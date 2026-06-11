from multi_agentic_rag.delta import compute_fact_deltas
from multi_agentic_rag.extraction.rule_extractors import extract_facts_from_text
from multi_agentic_rag.models import DocumentStatus, FactRecord
from multi_agentic_rag.retrieval.intent import QueryIntent, detect_intent


def test_rule_extractor_finds_thresholds() -> None:
    facts = extract_facts_from_text("REQ-1 The temperature threshold is 80 C over MQTT.")
    threshold_facts = [fact for fact in facts if fact.fact_type == "threshold"]

    assert threshold_facts
    assert threshold_facts[0].fact_key == "threshold:temperature"
    assert threshold_facts[0].value == "80"


def test_intent_router() -> None:
    assert detect_intent("What changed between versions?") == QueryIntent.DELTA_ANALYSIS
    assert detect_intent("Generate coverage") == QueryIntent.COVERAGE_GENERATION
    assert detect_intent("What was the old threshold?") == QueryIntent.HISTORICAL_TRUTH
    assert detect_intent("What is the current threshold?") == QueryIntent.CURRENT_TRUTH


def test_compute_fact_deltas_modified_threshold() -> None:
    old_fact = _fact("v1", "80")
    new_fact = _fact("v2", "95")

    deltas = compute_fact_deltas(
        system_name="SIIMCS",
        from_version="v1",
        to_version="v2",
        old_facts=[old_fact],
        new_facts=[new_fact],
    )

    assert len(deltas) == 1
    assert deltas[0].change_type == "modified"
    assert deltas[0].risk_level == "high"


def _fact(version: str, value: str) -> FactRecord:
    return FactRecord(
        fact_id=f"fact_{version}_{value}",
        fact_key="threshold:temperature",
        fact_type="threshold",
        value=value,
        unit="C",
        document_id=f"doc_{version}",
        chunk_id=f"chunk_{version}",
        system_name="SIIMCS",
        version=version,
        status=DocumentStatus.ACTIVE,
        evidence=f"temperature threshold is {value} C",
    )
