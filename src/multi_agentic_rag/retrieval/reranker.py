"""Reranking service interfaces."""

from __future__ import annotations

import asyncio
import math
import warnings
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator, model_validator

from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import RetrievalResult
from multi_agentic_rag.exceptions import ProviderCapabilityError, RetrievalQualityError
from multi_agentic_rag.infrastructure.embeddings.provider import (
    _configure_hf_token,
    _suppress_sentence_transformers_cache_warning,
)
from multi_agentic_rag.llm import GenerationConfig, ReasoningClient
from multi_agentic_rag.llm.azure_openai import AzureOpenAIReasoningClient
from multi_agentic_rag.runtime.device import resolve_device


class RerankingService(Protocol):
    """Reranker contract."""

    def rerank(self, query_text: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Rerank results.

        Args:
            query_text: Original user query.
            results: Candidate retrieval results after fusion.

        Returns:
            Results in final presentation order. Implementations may update
            scores and append source signals.
        """


class NoOpRerankingService:
    """Default reranker that preserves deterministic fused order."""

    def rerank(self, query_text: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Return results unchanged.

        Args:
            query_text: Original user query. It is accepted for interface
                compatibility and intentionally unused.
            results: Candidate retrieval results after fusion.

        Returns:
            The same results in the same order.
        """

        return results


class SentenceTransformerRerankingService:
    """Optional local cross-encoder reranker."""

    def __init__(
        self,
        model_name: str,
        *,
        hf_token: str | None = None,
        device: str = "auto",
        cache_dir: Path | None = None,
    ) -> None:
        """Initialize the lazy cross-encoder reranker.

        Args:
            model_name: Local or Hugging Face cross-encoder model name loaded on
                first rerank call.
            hf_token: Optional Hugging Face token used for Hub downloads.
            device: Target torch device. ``auto`` keeps sentence-transformers defaults.
        """

        self.model_name = model_name
        self.hf_token = hf_token
        self.device = device
        self.cache_dir = cache_dir
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is None:
            _configure_hf_token(self.hf_token)
            with warnings.catch_warnings(), _suppress_sentence_transformers_cache_warning():
                warnings.filterwarnings(
                    "ignore",
                    message=r"The Transformer `cache_dir` argument is deprecated.*",
                )
                module = import_module("sentence_transformers")
                kwargs: dict[str, Any] = {"token": self.hf_token}
                if not _uses_auto_device(self.device):
                    kwargs["device"] = self.device
                if self.cache_dir is not None:
                    kwargs["cache_folder"] = str(self.cache_dir)
                self._model = module.CrossEncoder(self.model_name, **kwargs)
        return self._model

    def rerank(self, query_text: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Rerank using a local cross-encoder.

        Args:
            query_text: Original user query.
            results: Candidate retrieval results after fusion.

        Returns:
            Results sorted by cross-encoder score with ``reranker`` added to the
            source signal list.
        """

        if not results:
            return []
        pairs = [(query_text, result.text) for result in results]
        scores = [float(score) for score in self._load().predict(pairs)]
        rescored = [
            result.model_copy(
                update={
                    "score": score,
                    "sources": [*result.sources, "reranker"],
                    "metadata": {**result.metadata, "reranker_score": score},
                }
            )
            for result, score in zip(results, scores, strict=True)
        ]
        return sorted(rescored, key=lambda item: (-item.score, item.chunk_id))


class AzureRankedCandidate(BaseModel):
    """One candidate ranking returned by Azure listwise reranking."""

    candidate_id: str
    rank: int = Field(ge=1)
    relevance_score: float = Field(ge=0.0, le=1.0)
    evidence_completeness_score: float = Field(ge=0.0, le=1.0)
    exactness_score: float = Field(ge=0.0, le=1.0)
    reason: str

    @field_validator("relevance_score", "evidence_completeness_score", "exactness_score")
    @classmethod
    def _finite_score(cls, value: float) -> float:
        if math.isnan(value) or math.isinf(value):
            raise ValueError("Reranker scores must be finite.")
        return value


class AzureQueryAnswerability(BaseModel):
    """Reranker answerability assessment."""

    answerable: bool
    confidence: float = Field(ge=0.0, le=1.0)
    missing_information: list[str] = Field(default_factory=list)


class AzureListwiseRerankerOutput(BaseModel):
    """Strict schema for Azure listwise reranking output."""

    ranked_candidates: list[AzureRankedCandidate] = Field(default_factory=list)
    query_answerability: AzureQueryAnswerability

    @model_validator(mode="after")
    def _contiguous_ranks(self) -> AzureListwiseRerankerOutput:
        ranks = [candidate.rank for candidate in self.ranked_candidates]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("Reranker ranks must be contiguous starting at 1.")
        return self


class AzureListwiseReranker:
    """Azure OpenAI listwise reranker with candidate-ID integrity checks."""

    def __init__(self, settings: Settings, reasoning_client: ReasoningClient) -> None:
        self.settings = settings
        self.reasoning_client = reasoning_client

    def rerank(self, query_text: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Run the async Azure reranker from synchronous callers."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.arerank(query_text, results))
        raise ProviderCapabilityError(
            "AzureListwiseReranker.rerank() was called inside an active event loop; "
            "use arerank() from async graph nodes."
        )

    async def arerank(
        self,
        query_text: str,
        results: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        """Rerank results with strict candidate set validation."""

        if not results:
            return []
        candidate_ids = [_candidate_id(result) for result in results]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise RetrievalQualityError("Azure reranker received duplicate candidate IDs.")
        prompt = _azure_reranker_prompt(query_text, results, candidate_ids)
        output = await self.reasoning_client.generate_structured(
            prompt=prompt,
            schema=AzureListwiseRerankerOutput,
            generation_config=GenerationConfig(
                temperature=self.settings.reranker_temperature,
                max_output_tokens=self.settings.reasoning_reranking_max_output_tokens,
                retry_count=self.settings.structured_generation_retry_count,
                task_name="listwise_reranking",
            ),
        )
        _validate_reranker_output(candidate_ids, output)
        by_id = {_candidate_id(result): result for result in results}
        reranked: list[RetrievalResult] = []
        for ranked in output.ranked_candidates:
            result = by_id[ranked.candidate_id]
            reranked.append(
                result.model_copy(
                    update={
                        "score": ranked.relevance_score,
                        "sources": [*result.sources, "azure_listwise_reranker"],
                        "metadata": {
                            **result.metadata,
                            "reranker_score": ranked.relevance_score,
                            "reranker_rank": ranked.rank,
                            "reranker_reason": ranked.reason,
                            "answerability": output.query_answerability.model_dump(mode="json"),
                        },
                    }
                )
            )
        return reranked[: self.settings.reranker_top_n]


def select_reranker(settings: Settings) -> RerankingService:
    """Select the configured reranker.

    Args:
        settings: Runtime configuration containing reranker provider and model
            values.

    Returns:
        Cross-encoder reranker when explicitly configured, otherwise the no-op
        deterministic reranker.
    """

    settings.ensure_project_cache_paths()
    if settings.reranker_provider == "azure_openai":
        return AzureListwiseReranker(settings, AzureOpenAIReasoningClient(settings))
    if settings.reranker_provider == "sentence_transformers" and settings.reranker_model:
        return SentenceTransformerRerankingService(
            settings.reranker_model,
            hf_token=settings.hf_token,
            device=resolve_device(settings.reranker_device, purpose="reranker").resolved,
            cache_dir=settings.sentence_transformers_home,
        )
    return NoOpRerankingService()


def _uses_auto_device(device: str) -> bool:
    return device.strip().lower() == "auto"


def _candidate_id(result: RetrievalResult) -> str:
    for key in ("semantic_unit_id", "evidence_id", "fact_id"):
        value = result.metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return result.chunk_id


def _azure_reranker_prompt(
    query_text: str,
    results: list[RetrievalResult],
    candidate_ids: list[str],
) -> str:
    payload = {
        "query": query_text,
        "instructions": (
            "Rank only the supplied candidates. Do not invent candidate IDs, do "
            "not modify candidate text, and do not add evidence."
        ),
        "candidates": [
            {
                "candidate_id": candidate_id,
                "excerpt": result.text[:1600],
                "requirement_ids": result.metadata.get("requirement_ids", []),
                "fact_ids": result.metadata.get("fact_ids", []),
                "evidence_ids": result.metadata.get("evidence_ids", []),
                "source_backend": result.sources,
                "raw_score": result.score,
                "rrf_score": result.metadata.get("rrf_score"),
                "deterministic_boosts": result.metadata.get("deterministic_boosts", []),
                "page": result.page,
                "section": result.metadata.get("section"),
                "version": result.version,
                "graph_path": result.metadata.get("graph_path", []),
            }
            for candidate_id, result in zip(candidate_ids, results, strict=True)
        ],
    }
    import json

    return json.dumps(payload, indent=2, ensure_ascii=False)


def _validate_reranker_output(
    candidate_ids: list[str],
    output: AzureListwiseRerankerOutput,
) -> None:
    supplied = set(candidate_ids)
    returned = [candidate.candidate_id for candidate in output.ranked_candidates]
    if len(set(returned)) != len(returned):
        raise RetrievalQualityError("Azure reranker returned duplicate candidate IDs.")
    invented = sorted(set(returned) - supplied)
    if invented:
        raise RetrievalQualityError("Azure reranker invented candidate IDs: " + ", ".join(invented))
    if not returned:
        raise RetrievalQualityError("Azure reranker returned no ranked candidates.")
