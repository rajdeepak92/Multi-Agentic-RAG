"""Evidence validation and ranking helpers."""

from __future__ import annotations

from collections.abc import Sequence

from multi_agentic_rag.domain import RankedRetrievalResult, RetrievalResult


class EvidenceValidator:
    """Validate that retrieval results can be traced to selected documents."""

    def validate(self, results: Sequence[RetrievalResult]) -> list[RankedRetrievalResult]:
        """Return ranked results that contain usable text and lineage.

        Args:
            results: Retrieval results from one or more backends.

        Returns:
            Ranked results with evidence paths. Results with missing text or
            untraceable lineage are dropped.
        """

        ranked: list[RankedRetrievalResult] = []
        for result in results:
            evidence_path = _evidence_path(result)
            if not evidence_path or not result.text.strip():
                continue
            payload = result.model_dump()
            payload["rank"] = len(ranked) + 1
            payload["evidence_path"] = evidence_path
            payload["metadata"] = {**result.metadata, "evidence_path": evidence_path}
            ranked.append(RankedRetrievalResult.model_validate(payload))
        return ranked

    def has_evidence(self, results: Sequence[RetrievalResult]) -> bool:
        """Return whether any result has traceable evidence."""

        return bool(self.validate(results))


def rank_retrieval_results(results: Sequence[RetrievalResult]) -> list[RankedRetrievalResult]:
    """Rank and validate retrieval results with the default validator."""

    return EvidenceValidator().validate(results)


def _evidence_path(result: RetrievalResult) -> list[str]:
    required = (
        result.system_name,
        result.kb_name,
        result.document_id,
        result.document_version_id,
        result.chunk_id,
        result.source_name,
        result.version,
    )
    if any(not value for value in required):
        return []
    if result.page < 1:
        return []
    return [
        f"System:{result.system_name}",
        f"KnowledgeBase:{result.kb_name}",
        f"Document:{result.document_id}",
        f"DocumentVersion:{result.document_version_id}",
        f"Version:{result.version}",
        f"Chunk:{result.chunk_id}",
        f"Source:{result.source_name}#page={result.page}",
    ]
