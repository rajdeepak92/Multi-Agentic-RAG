from __future__ import annotations

from multi_agentic_rag.domain import DocumentStatus, FactRecord
from multi_agentic_rag.quality.facts import evaluate_fact_quality, validate_facts
from multi_agentic_rag.quality.retrieval import evaluate_retrieval_results


def test_fact_evidence_numeric_unit_duplicate_and_contradiction_checks() -> None:
    facts = [
        _fact("fact-1", "threshold:temperature:max", "50-70", "°C"),
        _fact("fact-2", "threshold:temperature:max", "50-70", "°C"),
        _fact("fact-3", "threshold:temperature:max", "80-70", "°C"),
        _fact(
            "fact-4",
            "threshold:pressure:max",
            "8-10",
            "psi",
            evidence="Pressure Sensor 8-10 bar",
        ),
    ]

    report = validate_facts(facts)

    assert report.duplicate_count == 1
    assert report.contradiction_count == 3
    assert report.numeric_error_count == 1
    assert report.unit_error_count == 1


def test_fact_quality_requires_golden_dataset_for_precision_recall() -> None:
    facts = [_fact("fact-1", "threshold:temperature:max", "50-70", "°C")]
    golden = [
        {
            "fact_key": "threshold:temperature:max",
            "value": "50-70",
            "unit": "°C",
        }
    ]

    report = evaluate_fact_quality(facts, golden)

    assert report["precision"] == 1.0
    assert report["recall"] == 1.0
    assert report["f1"] == 1.0


def test_retrieval_metrics_calculate_precision_recall_mrr_and_ndcg() -> None:
    dataset = [
        {
            "query_id": "Q-001",
            "expected_requirement_ids": ["BR-1"],
            "expected_fact_ids": ["fact-1"],
            "expected_pages": [5],
            "expected_sections": ["Section"],
            "must_include_values": ["50-70°C"],
        }
    ]
    results = {
        "Q-001": [
            {
                "chunk_id": "chunk-a",
                "requirement_ids": ["BR-1"],
                "fact_ids": [],
                "page": 5,
                "section": "Section",
                "text": "Requirement evidence",
            },
            {
                "chunk_id": "chunk-b",
                "requirement_ids": [],
                "fact_ids": ["fact-1"],
                "page": 5,
                "section": "Section",
                "text": "Temperature max 50-70°C",
            },
        ]
    }

    report = evaluate_retrieval_results(dataset, results, k=2)
    row = report["rows"][0]

    assert row["precision_at_k"] == 1.0
    assert row["recall_at_k"] == 1.0
    assert row["mrr"] == 1.0
    assert row["ndcg_at_k"] == 1.0
    assert row["numeric_answer_recall"] == 1.0


def _fact(
    fact_id: str,
    fact_key: str,
    value: str,
    unit: str | None,
    *,
    evidence: str | None = None,
) -> FactRecord:
    return FactRecord(
        fact_id=fact_id,
        fact_key=fact_key,
        fact_type="threshold",
        value=value,
        unit=unit,
        document_version_id="version",
        document_id="doc",
        chunk_id="chunk",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        status=DocumentStatus.ACTIVE,
        evidence=evidence or f"Temperature Sensor {value}{unit or ''}",
        requirement_id=None,
        semantic_key=fact_key,
        metadata={},
    )
