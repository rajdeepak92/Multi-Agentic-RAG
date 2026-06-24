"""Retrieval-quality metrics for labelled benchmarks and runtime proxies."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel


class RetrievalMetricRow(BaseModel):
    """Metric row for one labelled retrieval query."""

    query_id: str
    precision_at_k: float
    recall_at_k: float
    mrr: float
    ndcg_at_k: float
    hit_rate_at_k: float
    exact_id_recall: float
    fact_recall: float
    page_accuracy: float
    section_accuracy: float
    numeric_answer_recall: float
    source: str = "fusion"


def evaluate_retrieval_results(
    dataset: list[dict[str, Any]],
    results_by_query_id: dict[str, list[dict[str, Any]]],
    *,
    k: int = 10,
    source: str = "fusion",
) -> dict[str, Any]:
    """Calculate labelled retrieval benchmark metrics."""

    rows = [
        _evaluate_query(record, results_by_query_id.get(str(record["query_id"]), []), k, source)
        for record in dataset
    ]
    if not rows:
        return {"rows": [], "summary": {}}
    summary = {
        "query_count": len(rows),
        "precision_at_k": _mean(row.precision_at_k for row in rows),
        "recall_at_k": _mean(row.recall_at_k for row in rows),
        "mrr": _mean(row.mrr for row in rows),
        "ndcg_at_k": _mean(row.ndcg_at_k for row in rows),
        "hit_rate_at_k": _mean(row.hit_rate_at_k for row in rows),
        "exact_id_recall": _mean(row.exact_id_recall for row in rows),
        "fact_recall": _mean(row.fact_recall for row in rows),
        "page_accuracy": _mean(row.page_accuracy for row in rows),
        "section_accuracy": _mean(row.section_accuracy for row in rows),
        "numeric_answer_recall": _mean(row.numeric_answer_recall for row in rows),
    }
    return {
        "rows": [row.model_dump(mode="json") for row in rows],
        "summary": summary,
    }


def runtime_retrieval_proxies(
    results: list[dict[str, Any]],
    *,
    target_requirement_ids: set[str] | None = None,
    target_fact_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Calculate runtime proxies without pretending they are labelled metrics."""

    target_requirement_ids = target_requirement_ids or set()
    target_fact_ids = target_fact_ids or set()
    requirement_ids = {
        item
        for result in results
        for item in result.get(
            "requirement_ids",
            result.get("metadata", {}).get("requirement_ids", []),
        )
    }
    fact_ids = {
        item
        for result in results
        for item in result.get("fact_ids", result.get("metadata", {}).get("fact_ids", []))
    }
    candidate_ids = [
        str(result.get("candidate_id") or result.get("chunk_id") or "")
        for result in results
    ]
    duplicate_count = len(candidate_ids) - len(set(candidate_ids))
    return {
        "evidence_count": len(results),
        "target_requirement_coverage": _coverage(requirement_ids, target_requirement_ids),
        "target_fact_coverage": _coverage(fact_ids, target_fact_ids),
        "duplicate_rate": duplicate_count / len(candidate_ids) if candidate_ids else 0.0,
        "source_diversity": len(
            {
                source
                for result in results
                for source in result.get("sources", result.get("source_backend", []))
            }
        ),
        "citation_completeness": _citation_completeness(results),
    }


def render_retrieval_quality_markdown(report: dict[str, Any]) -> str:
    """Render a concise Markdown retrieval-quality report."""

    summary = report.get("summary", {})
    lines = [
        "# Retrieval Quality Report",
        "",
        f"- Query count: {summary.get('query_count', 0)}",
        f"- Precision@K: {_metric(summary.get('precision_at_k'))}",
        f"- Recall@K: {_metric(summary.get('recall_at_k'))}",
        f"- MRR: {_metric(summary.get('mrr'))}",
        f"- nDCG@K: {_metric(summary.get('ndcg_at_k'))}",
        f"- Hit Rate@K: {_metric(summary.get('hit_rate_at_k'))}",
        f"- Exact-ID recall: {_metric(summary.get('exact_id_recall'))}",
        f"- Fact recall: {_metric(summary.get('fact_recall'))}",
        f"- Page accuracy: {_metric(summary.get('page_accuracy'))}",
        f"- Section accuracy: {_metric(summary.get('section_accuracy'))}",
        f"- Numeric answer recall: {_metric(summary.get('numeric_answer_recall'))}",
    ]
    return "\n".join(lines) + "\n"


def _evaluate_query(
    record: dict[str, Any],
    results: list[dict[str, Any]],
    k: int,
    source: str,
) -> RetrievalMetricRow:
    top = results[:k]
    expected_requirement_ids = set(record.get("expected_requirement_ids", []))
    expected_fact_ids = set(record.get("expected_fact_ids", []))
    expected_pages = {int(page) for page in record.get("expected_pages", [])}
    expected_sections = set(record.get("expected_sections", []))
    expected_values = {str(value) for value in record.get("must_include_values", [])}
    expected_ids = expected_requirement_ids | expected_fact_ids
    hits = [_is_relevant(result, expected_requirement_ids, expected_fact_ids) for result in top]
    relevant_count = sum(1 for hit in hits if hit)
    first_hit_index = next((index for index, hit in enumerate(hits, start=1) if hit), None)
    result_requirement_ids = {
        item for result in top for item in _list_field(result, "requirement_ids")
    }
    result_fact_ids = {item for result in top for item in _list_field(result, "fact_ids")}
    result_pages = {int(result["page"]) for result in top if result.get("page") is not None}
    result_sections = {
        str(result.get("section"))
        for result in top
        if result.get("section") not in {None, ""}
    }
    concatenated = "\n".join(
        str(result.get("text") or result.get("excerpt") or "")
        for result in top
    )
    return RetrievalMetricRow(
        query_id=str(record["query_id"]),
        precision_at_k=relevant_count / k if k else 0.0,
        recall_at_k=relevant_count / len(expected_ids) if expected_ids else 1.0,
        mrr=1.0 / first_hit_index if first_hit_index else 0.0,
        ndcg_at_k=_ndcg(hits),
        hit_rate_at_k=1.0 if relevant_count else 0.0,
        exact_id_recall=_coverage(result_requirement_ids, expected_requirement_ids),
        fact_recall=_coverage(result_fact_ids, expected_fact_ids),
        page_accuracy=_coverage(result_pages, expected_pages),
        section_accuracy=_coverage(result_sections, expected_sections),
        numeric_answer_recall=_value_recall(concatenated, expected_values),
        source=source,
    )


def _is_relevant(
    result: dict[str, Any],
    expected_requirement_ids: set[str],
    expected_fact_ids: set[str],
) -> bool:
    requirement_ids = set(_list_field(result, "requirement_ids"))
    fact_ids = set(_list_field(result, "fact_ids"))
    return bool((requirement_ids & expected_requirement_ids) or (fact_ids & expected_fact_ids))


def _list_field(result: dict[str, Any], field: str) -> list[str]:
    value = result.get(field)
    if value is None:
        value = result.get("metadata", {}).get(field)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _coverage(actual: set[Any], expected: set[Any]) -> float:
    if not expected:
        return 1.0
    return len(actual & expected) / len(expected)


def _value_recall(text: str, expected_values: set[str]) -> float:
    if not expected_values:
        return 1.0
    compact = text.replace(" ", "").lower()
    return sum(1 for value in expected_values if value.replace(" ", "").lower() in compact) / len(
        expected_values
    )


def _ndcg(hits: list[bool]) -> float:
    dcg = sum((1.0 if hit else 0.0) / math.log2(index + 1) for index, hit in enumerate(hits, 1))
    ideal_hits = sorted(hits, reverse=True)
    idcg = sum(
        (1.0 if hit else 0.0) / math.log2(index + 1)
        for index, hit in enumerate(ideal_hits, 1)
    )
    return dcg / idcg if idcg else 0.0


def _citation_completeness(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    complete = 0
    for result in results:
        if (
            result.get("source_name")
            and result.get("page") is not None
            and (result.get("chunk_id") or result.get("semantic_unit_id"))
        ):
            complete += 1
    return complete / len(results)


def _mean(values: Any) -> float:
    items = [float(value) for value in values]
    return sum(items) / len(items) if items else 0.0


def _metric(value: Any) -> str:
    if isinstance(value, int | float):
        return f"{float(value):.3f}"
    return "not calculated"
