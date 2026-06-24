from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import RetrievalResult
from multi_agentic_rag.exceptions import (
    GenerationTokenLimitError,
    ProviderCapabilityError,
    RetrievalQualityError,
    StructuredGenerationError,
)
from multi_agentic_rag.infrastructure.embeddings.provider import AzureOpenAIEmbeddingProvider
from multi_agentic_rag.llm.azure_openai import (
    AzureDeploymentCapability,
    AzureOpenAIReasoningClient,
    azure_preflight,
)
from multi_agentic_rag.llm.structured import GenerationConfig, LLMGeneratedUserStoryBatch
from multi_agentic_rag.retrieval.reranker import (
    AzureListwiseReranker,
    AzureListwiseRerankerOutput,
)


def _azure_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "postgres_dsn": "postgresql+asyncpg://x",
        "reasoning_provider": "azure_openai",
        "azure_openai_endpoint": "https://example.openai.azure.com",
        "azure_openai_api_key": "test-key",
        "azure_openai_api_version": "2024-10-21",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_azure_preflight_redacts_and_routes_configured_deployments() -> None:
    settings = _azure_settings()

    manifest = azure_preflight(
        settings,
        deployment_capabilities={
            "gpt-5.2-chat": AzureDeploymentCapability(
                deployment="gpt-5.2-chat",
                reachable=True,
                api_style="responses",
                structured_output=True,
                max_output_tokens=20000,
            ),
            "gpt-4o-mini": AzureDeploymentCapability(
                deployment="gpt-4o-mini",
                reachable=True,
                api_style="responses",
                structured_output=True,
                max_output_tokens=8192,
            ),
            "text-embedding-3-large": AzureDeploymentCapability(
                deployment="text-embedding-3-large",
                reachable=True,
                api_style="embeddings",
                embedding_dimensions=3072,
            ),
        },
    )

    redacted = manifest.redacted_manifest()
    assert redacted["api_key_configured"] is True
    assert redacted["deployments"]["generation"]["deployment"] == "gpt-5.2-chat"
    assert "test-key" not in str(redacted)


def test_azure_preflight_rejects_unsupported_output_budget() -> None:
    settings = _azure_settings(reasoning_generation_max_output_tokens=4096)

    with pytest.raises(ProviderCapabilityError):
        azure_preflight(
            settings,
            deployment_capabilities={
                "gpt-5.2-chat": AzureDeploymentCapability(
                    deployment="gpt-5.2-chat",
                    max_output_tokens=1024,
                ),
                "gpt-4o-mini": AzureDeploymentCapability(
                    deployment="gpt-4o-mini",
                    max_output_tokens=8192,
                ),
                "text-embedding-3-large": AzureDeploymentCapability(
                    deployment="text-embedding-3-large"
                ),
            },
        )


def test_azure_reasoning_routes_story_generation_to_generation_deployment() -> None:
    fake = FakeAzureClient(
        response=SimpleNamespace(
            output_text='{"stories":[],"reasoning_summary":"ok"}',
            id="req-1",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
    )
    client = AzureOpenAIReasoningClient(_azure_settings(), client=fake)

    result = asyncio.run(
        client.generate_structured(
            prompt="generate",
            schema=LLMGeneratedUserStoryBatch,
            generation_config=GenerationConfig(
                task_name="user_story_generation",
                max_output_tokens=100,
            ),
        )
    )

    assert result.reasoning_summary == "ok"
    assert fake.responses.calls[0]["model"] == "gpt-5.2-chat"


def test_azure_reasoning_truncation_raises_token_limit_error() -> None:
    fake = FakeAzureClient(
        response=SimpleNamespace(
            output_text='{"stories":[],"reasoning_summary":"partial"}',
            choices=[SimpleNamespace(finish_reason="length")],
        )
    )
    client = AzureOpenAIReasoningClient(_azure_settings(), client=fake)

    with pytest.raises(GenerationTokenLimitError):
        asyncio.run(
            client.generate_structured(
                prompt="generate",
                schema=LLMGeneratedUserStoryBatch,
                generation_config=GenerationConfig(
                    task_name="user_story_generation",
                    max_output_tokens=100,
                ),
            )
        )


def test_azure_reasoning_invalid_structured_output_raises_schema_error() -> None:
    fake = FakeAzureClient(response=SimpleNamespace(output_text='{"stories":"bad"}'))
    client = AzureOpenAIReasoningClient(_azure_settings(), client=fake)

    with pytest.raises(StructuredGenerationError):
        asyncio.run(
            client.generate_structured(
                prompt="generate",
                schema=LLMGeneratedUserStoryBatch,
                generation_config=GenerationConfig(
                    task_name="user_story_generation",
                    max_output_tokens=100,
                ),
            )
        )


def test_azure_embedding_preserves_order_and_validates_dimension() -> None:
    provider = AzureOpenAIEmbeddingProvider(
        _azure_settings(
            embedding_provider="azure_openai",
            embedding_expected_dimension=3,
            embedding_deployment="text-embedding-3-large",
        ),
        client=FakeEmbeddingClient(
            [
                SimpleNamespace(index=1, embedding=[0.4, 0.5, 0.6]),
                SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3]),
            ]
        ),
    )

    assert provider.embed_documents(["a", "b"]) == [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]


def test_azure_embedding_dimension_mismatch_fails() -> None:
    provider = AzureOpenAIEmbeddingProvider(
        _azure_settings(
            embedding_provider="azure_openai",
            embedding_expected_dimension=3,
            embedding_deployment="text-embedding-3-large",
        ),
        client=FakeEmbeddingClient([SimpleNamespace(index=0, embedding=[0.1, 0.2])]),
    )

    with pytest.raises(ProviderCapabilityError):
        provider.embed_query("query")


def test_azure_embedding_rejects_nan_vector() -> None:
    provider = AzureOpenAIEmbeddingProvider(
        _azure_settings(
            embedding_provider="azure_openai",
            embedding_expected_dimension=3,
            embedding_deployment="text-embedding-3-large",
        ),
        client=FakeEmbeddingClient([SimpleNamespace(index=0, embedding=[0.1, float("nan"), 0.2])]),
    )

    with pytest.raises(ProviderCapabilityError):
        provider.embed_query("query")


def test_azure_reranker_rejects_invented_candidate_ids() -> None:
    reranker = AzureListwiseReranker(
        _azure_settings(reranker_provider="azure_openai"),
        FakeRerankerReasoner(
            AzureListwiseRerankerOutput.model_validate(
                {
                    "ranked_candidates": [
                        {
                            "candidate_id": "invented",
                            "rank": 1,
                            "relevance_score": 0.9,
                            "evidence_completeness_score": 0.9,
                            "exactness_score": 0.9,
                            "reason": "bad id",
                        }
                    ],
                    "query_answerability": {
                        "answerable": True,
                        "confidence": 0.9,
                        "missing_information": [],
                    },
                }
            )
        ),
    )

    with pytest.raises(RetrievalQualityError):
        asyncio.run(reranker.arerank("query", [_retrieval_result("chunk-1")]))


class FakeAzureClient:
    def __init__(self, *, response: Any) -> None:
        self.responses = FakeResponses(response)


class FakeResponses:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class FakeEmbeddingClient:
    def __init__(self, data: list[Any]) -> None:
        self.embeddings = self
        self.data = data

    def create(self, **_: Any) -> Any:
        return SimpleNamespace(data=self.data, usage={"total_tokens": 1})


class FakeRerankerReasoner:
    model = "gpt-4o-mini"
    prompt_version = "test"

    def __init__(self, output: AzureListwiseRerankerOutput) -> None:
        self.output = output

    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: type[Any],
        generation_config: GenerationConfig,
    ) -> Any:
        assert schema is AzureListwiseRerankerOutput
        assert generation_config.task_name == "listwise_reranking"
        assert "chunk-1" in prompt
        return self.output


def _retrieval_result(chunk_id: str) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        document_id="doc",
        document_version_id="version",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        source_name="source.pdf",
        page=1,
        text="exact evidence",
        score=1.0,
        sources=["postgres"],
        metadata={},
    )
