"""Document-scoped deterministic chat agent."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from multi_agentic_rag.domain import RankedRetrievalResult, RetrievalResult
from multi_agentic_rag.retrieval.evidence import EvidenceValidator

EVIDENCE_NOT_FOUND_MESSAGE = "I could not find this in the selected project documents"


class ChatRetriever(Protocol):
    """Retriever contract used by the document-scoped chat agent."""

    async def retrieve(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str = "default",
        version: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Retrieve document-scoped evidence."""


class DocumentScopedAnswer(BaseModel):
    """Deterministic answer with evidence trace."""

    answer: str
    refused: bool
    evidence: list[RankedRetrievalResult] = Field(default_factory=list)


class DocumentScopedChatAgent:
    """Answer only from retrievable, traceable project-document evidence."""

    def __init__(
        self,
        retriever: ChatRetriever,
        *,
        evidence_validator: EvidenceValidator | None = None,
    ) -> None:
        """Create the chat agent.

        Args:
            retriever: Configured retriever scoped by system, knowledge base,
                and optional document version.
            evidence_validator: Optional validator override for tests or
                stricter downstream policies.
        """

        self.retriever = retriever
        self.evidence_validator = evidence_validator or EvidenceValidator()

    async def answer(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str = "default",
        version: str | None = None,
        top_k: int = 5,
    ) -> DocumentScopedAnswer:
        """Return a deterministic evidence answer or refusal.

        Args:
            query_text: User question.
            system_name: System scope.
            kb_name: Knowledge-base scope.
            version: Optional document version filter.
            top_k: Maximum evidence chunks to retrieve and render.

        Returns:
            Refusal when no traceable evidence exists; otherwise a concise
            evidence-only answer.
        """

        results = await self.retriever.retrieve(
            query_text,
            system_name=system_name,
            kb_name=kb_name,
            version=version,
            top_k=top_k,
        )
        evidence = self.evidence_validator.validate(results)
        if not evidence:
            return DocumentScopedAnswer(
                answer=EVIDENCE_NOT_FOUND_MESSAGE,
                refused=True,
                evidence=[],
            )
        return DocumentScopedAnswer(
            answer=_render_evidence(evidence[:top_k]),
            refused=False,
            evidence=evidence[:top_k],
        )


def _render_evidence(evidence: list[RankedRetrievalResult]) -> str:
    lines = ["Selected project document evidence:"]
    for result in evidence:
        snippet = " ".join(result.text.split())
        if len(snippet) > 320:
            snippet = f"{snippet[:317]}..."
        lines.append(
            f"- [{result.source_name} page {result.page}, {result.version}] {snippet}"
        )
    return "\n".join(lines)
