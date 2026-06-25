from __future__ import annotations

import asyncio
import types
from types import SimpleNamespace
from typing import Any

import pytest
from openai import AzureOpenAI

from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import RetrievalResult
from multi_agentic_rag.exceptions import ConfigError, ProviderCapabilityError, RetrievalQualityError
from multi_agentic_rag.infrastructure.azure_openai_client import (
    build_azure_openai_client,
    normalize_azure_endpoint,
)
from multi_agentic_rag.infrastructure.embeddings.provider import AzureOpenAIEmbeddingProvider
from multi_agentic_rag.llm.azure_openai import (
    AzureDeploymentRouter,
    AzureOpenAIReasoningClient,
)
from multi_agentic_rag.llm.openai_reasoning import OpenAIReasoningClient
from multi_agentic_rag.llm.structured import GenerationConfig, LLMGeneratedUserStoryBatch
from multi_agentic_rag.retrieval.reranker import (
    AzureListwiseReranker,
    AzureListwiseRerankerOutput,
    select_reranker,
)


def _azure_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "postgres_dsn": "postgresql+asyncpg://x",
        "reasoning_provider": "azure_openai",
        "embedding_provider": "azure_openai",
        "reranker_provider": "azure_openai",
        "azure_openai_endpoint": "https://example.openai.azure.com",
        "azure_openai_api_key": "test-key",
        "azure_openai_api_version": "2024-12-01-preview",
        "azure_openai_generation_deployment": "gpt-5.2-chat",
        "azure_openai_answer_deployment": "gpt-5.2-chat",
        "azure_openai_analysis_deployment": "gpt-5.2-chat",
        "azure_openai_utility_deployment": "gpt-4o-mini",
        "azure_openai_validation_deployment": "gpt-4o-mini",
        "azure_openai_reranker_deployment": "gpt-4o-mini",
        "azure_openai_embedding_deployment": "text-embedding-3-large",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_public_openai_reasoning_uses_openai_sdk_without_azure_config(monkeypatch) -> None:
    created: list[dict[str, Any]] = []

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

    fake_module = types.SimpleNamespace(OpenAI=FakeOpenAI)
    monkeypatch.setattr(
        "multi_agentic_rag.llm.openai_reasoning.import_module", lambda _: fake_module
    )

    settings = Settings(
        postgres_dsn="postgresql+asyncpg://x",
        openai_api_key="openai-key",
        _env_file=None,
    )
    client = OpenAIReasoningClient(settings)

    assert client._get_client() is client._get_client()
    assert created == [{"api_key": "openai-key"}]


def test_azure_openai_client_factory_builds_native_client() -> None:
    client = build_azure_openai_client(_azure_settings())

    assert isinstance(client, AzureOpenAI)


@pytest.mark.parametrize(
    ("endpoint", "message"),
    [
        ("https://example.openai.azure.com/api/projects/foo", "resource root"),
        ("https://example.openai.azure.com/openai/v1/", "resource root"),
        ("http://example.openai.azure.com", "HTTPS"),
        ("https://example.openai.azure.com?x=1", "query string"),
    ],
)
def test_normalize_azure_endpoint_rejects_invalid_urls(endpoint: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        normalize_azure_endpoint(endpoint)


def test_normalize_azure_endpoint_accepts_root_host() -> None:
    assert (
        normalize_azure_endpoint(" https://example.cognitiveservices.azure.com/ ")
        == "https://example.cognitiveservices.azure.com"
    )


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"azure_openai_endpoint": None}, "AZURE_OPENAI_ENDPOINT"),
        ({"azure_openai_api_key": None}, "AZURE_OPENAI_API_KEY"),
        ({"azure_openai_api_version": None}, "AZURE_OPENAI_API_VERSION"),
    ],
)
def test_azure_client_factory_requires_endpoint_key_and_version(
    overrides: dict[str, Any],
    match: str,
) -> None:
    values = {
        "azure_openai_endpoint": "https://example.openai.azure.com",
        "azure_openai_api_key": "test-key",
        "azure_openai_api_version": "2024-12-01-preview",
        "azure_openai_request_timeout_seconds": 180.0,
        "azure_openai_max_retries": 3,
    }
    values.update(overrides)
    settings = SimpleNamespace(**values)

    with pytest.raises(ConfigError, match=match):
        build_azure_openai_client(settings)


def test_azure_settings_rejects_stale_base_url_when_azure_is_selected() -> None:
    with pytest.raises(ConfigError, match="deprecated"):
        _azure_settings(azure_openai_base_url="https://example.openai.azure.com/openai/v1/")


def test_azure_deployment_router_covers_all_tasks() -> None:
    router = AzureDeploymentRouter(_azure_settings())

    assert router.deployment_for_task("user_story_generation") == "gpt-5.2-chat"
    assert router.deployment_for_task("answer_synthesis") == "gpt-5.2-chat"
    assert router.deployment_for_task("requirement_group_analysis") == "gpt-5.2-chat"
    assert router.deployment_for_task("quality_validation_report") == "gpt-4o-mini"
    assert router.deployment_for_task("reranking") == "gpt-4o-mini"
    assert router.deployment_for_task("task_intent") == "gpt-4o-mini"
    assert router.deployment_for_task("workflow_plan") == "gpt-4o-mini"
    assert router.deployment_for_task("fact_review") == "gpt-4o-mini"


def test_azure_reasoning_injected_client_is_preserved() -> None:
    fake = FakeResponsesAzureClient(
        response=SimpleNamespace(output_text='{"stories":[],"reasoning_summary":"ok"}', id="req-1")
    )
    client = AzureOpenAIReasoningClient(_azure_settings(), client=fake)

    assert client._get_client() is fake


def test_azure_reasoning_chat_completions_request_uses_gpt5_token_parameter() -> None:
    fake = FakeChatAzureClient(
        response=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"stories":[],"reasoning_summary":"ok"}'),
                    finish_reason="stop",
                )
            ],
            id="req-1",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
    )
    client = AzureOpenAIReasoningClient(
        _azure_settings(azure_openai_reasoning_api_style="chat_completions"),
        client=fake,
    )

    asyncio.run(
        client.generate_structured(
            prompt="generate",
            schema=LLMGeneratedUserStoryBatch,
            generation_config=GenerationConfig(
                task_name="user_story_generation", max_output_tokens=64
            ),
        )
    )

    call = fake.chat.completions.calls[0]
    assert call["model"] == "gpt-5.2-chat"
    assert "temperature" not in call
    assert call["max_completion_tokens"] == 64
    assert call["response_format"]["type"] == "json_schema"


def test_azure_reasoning_chat_completions_uses_max_tokens_for_older_deployments() -> None:
    fake = FakeChatAzureClient(
        response=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"stories":[],"reasoning_summary":"ok"}'),
                    finish_reason="stop",
                )
            ],
            id="req-1",
        )
    )
    client = AzureOpenAIReasoningClient(
        _azure_settings(
            azure_openai_reasoning_api_style="chat_completions",
            azure_openai_generation_deployment="gpt-4o-mini",
        ),
        client=fake,
    )

    asyncio.run(
        client.generate_structured(
            prompt="generate",
            schema=LLMGeneratedUserStoryBatch,
            generation_config=GenerationConfig(
                task_name="user_story_generation", max_output_tokens=64
            ),
        )
    )

    call = fake.chat.completions.calls[0]
    assert call["model"] == "gpt-4o-mini"
    assert call["max_tokens"] == 64
    assert call["temperature"] == 0.0


def test_azure_reasoning_responses_request_uses_native_schema_payload() -> None:
    fake = FakeResponsesAzureClient(
        response=SimpleNamespace(output_text='{"stories":[],"reasoning_summary":"ok"}', id="req-1")
    )
    client = AzureOpenAIReasoningClient(
        _azure_settings(azure_openai_reasoning_api_style="responses"),
        client=fake,
    )

    asyncio.run(
        client.generate_structured(
            prompt="generate",
            schema=LLMGeneratedUserStoryBatch,
            generation_config=GenerationConfig(
                task_name="user_story_generation", max_output_tokens=64
            ),
        )
    )

    call = fake.responses.calls[0]
    assert call["model"] == "gpt-5.2-chat"
    assert call["max_output_tokens"] == 64
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["input"].startswith("{")


def test_azure_embedding_preserves_order_and_dimensions() -> None:
    provider = AzureOpenAIEmbeddingProvider(
        _azure_settings(
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

    assert provider.embed_documents(["a", "b"]) == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert provider.request_diagnostics[0]["validated_dimension"] == 3


def test_azure_embedding_request_includes_dimensions_when_configured() -> None:
    client = FakeEmbeddingClient([SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3])])
    provider = AzureOpenAIEmbeddingProvider(
        _azure_settings(
            embedding_expected_dimension=3,
            embedding_deployment="text-embedding-3-large",
        ),
        client=client,
    )

    provider.embed_query("query")

    assert client.calls[0]["dimensions"] == 3


def test_azure_embedding_rejects_nan_vector() -> None:
    provider = AzureOpenAIEmbeddingProvider(
        _azure_settings(
            embedding_expected_dimension=3,
            embedding_deployment="text-embedding-3-large",
        ),
        client=FakeEmbeddingClient([SimpleNamespace(index=0, embedding=[0.1, float("nan"), 0.2])]),
    )

    with pytest.raises(ProviderCapabilityError):
        provider.embed_query("query")


def test_azure_reranker_rejects_invented_candidate_ids() -> None:
    reranker = AzureListwiseReranker(
        _azure_settings(),
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


def test_azure_reranker_independent_from_reasoning_provider(monkeypatch) -> None:
    created: list[str] = []

    class FakeReasoner:
        model = "gpt-4o-mini"
        prompt_version = "test"

        async def generate_structured(
            self,
            *,
            prompt: str,
            schema: type[Any],
            generation_config: GenerationConfig,
        ) -> Any:
            assert schema is AzureListwiseRerankerOutput
            return AzureListwiseRerankerOutput.model_validate(
                {
                    "ranked_candidates": [
                        {
                            "candidate_id": "chunk-1",
                            "rank": 1,
                            "relevance_score": 1.0,
                            "evidence_completeness_score": 1.0,
                            "exactness_score": 1.0,
                            "reason": "best",
                        }
                    ],
                    "query_answerability": {
                        "answerable": True,
                        "confidence": 1.0,
                        "missing_information": [],
                    },
                }
            )

    def fake_factory(settings: Settings) -> FakeReasoner:
        created.append(settings.reasoning_provider)
        return FakeReasoner()

    monkeypatch.setattr(
        "multi_agentic_rag.retrieval.reranker.AzureOpenAIReasoningClient", fake_factory
    )

    reranker = select_reranker(
        _azure_settings(reasoning_provider="openai", reranker_provider="azure_openai")
    )

    assert created == ["openai"]
    assert isinstance(reranker, AzureListwiseReranker)


class FakeResponsesAzureClient:
    def __init__(self, *, response: Any) -> None:
        self.responses = FakeResponses(response)


class FakeChatAzureClient:
    def __init__(self, *, response: Any) -> None:
        self.chat = SimpleNamespace(completions=FakeChatCompletions(response))


class FakeResponses:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class FakeChatCompletions:
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
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
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
