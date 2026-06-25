"""Azure OpenAI provider integration with task-specific deployment routing."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from pydantic import BaseModel, Field, ValidationError

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.domain import (
    EvidenceBundle,
    FactEnrichmentBatch,
    GeneratedUserStory,
    GeneratedUserStoryBatch,
    GroundedAnswer,
    QualityValidationReport,
    TaskIntent,
    WorkflowPlan,
)
from multi_agentic_rag.exceptions import (
    ConfigError,
    GenerationTokenLimitError,
    ProviderCapabilityError,
    StructuredGenerationError,
)
from multi_agentic_rag.infrastructure.azure_openai_client import (
    build_azure_openai_client,
    normalize_azure_endpoint,
)
from multi_agentic_rag.llm.prompts import (
    ANSWER_SYNTHESIS_PROMPT,
    FACT_ENRICHMENT_PROMPT,
    INTENT_ROUTER_PROMPT,
    PROMPT_VERSION,
    QUALITY_VALIDATION_PROMPT,
    USER_STORY_PROMPT,
    WORKFLOW_PLANNER_PROMPT,
)
from multi_agentic_rag.llm.structured import (
    GenerationConfig,
    LLMGeneratedUserStoryBatch,
    LLMQualityValidationReport,
    strict_openai_schema,
)
from multi_agentic_rag.runtime.secrets import redact_secrets

T = TypeVar("T", bound=BaseModel)

__all__ = [
    "AzureDeploymentRouter",
    "AzureOpenAICapabilityManifest",
    "AzureOpenAIReasoningClient",
    "azure_preflight",
    "normalize_azure_endpoint",
]


@dataclass(frozen=True)
class AzureDeploymentRouter:
    """Resolve the configured Azure deployment for each GraphRAG task."""

    settings: Settings

    def deployment_for_task(self, task_name: str) -> str:
        """Return the configured deployment for a logical task name."""

        normalized = task_name.strip().lower()
        if normalized in {
            "user_story_generation",
            "final_user_story_generation",
            "story_outline_generation",
        }:
            return self.settings.azure_openai_generation_deployment
        if normalized in {"answer_synthesis", "grounded_answer", "ask_synthesis"}:
            return self.settings.azure_openai_answer_deployment
        if normalized in {"requirement_group_analysis", "story_group_analysis"}:
            return self.settings.azure_openai_analysis_deployment
        if normalized in {"quality_validation_report", "story_validation", "validate_user_story"}:
            return self.settings.azure_openai_validation_deployment
        if normalized in {"listwise_reranking", "reranking", "reranker"}:
            return self.settings.azure_openai_reranker_deployment
        if normalized in {
            "retrieval_plan",
            "query_planning",
            "query_expansion",
            "evidence_assessment",
            "fact_review",
            "fact_candidate_review",
            "fact_enrichment_batch",
            "task_intent",
            "workflow_plan",
        }:
            return self.settings.azure_openai_utility_deployment
        return self.settings.azure_openai_utility_deployment


class AzureDeploymentCapability(BaseModel):
    """Cached capability record for one Azure deployment."""

    deployment: str
    reachable: bool = False
    api_style: str = "unknown"
    structured_output: bool = False
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    embedding_dimensions: int | None = None
    error: str | None = None


class AzureOpenAICapabilityManifest(BaseModel):
    """Redacted preflight result for configured Azure OpenAI deployments."""

    provider: str = "azure_openai"
    client_class: str = "AzureOpenAI"
    endpoint: str
    reasoning_api_style: str
    api_version_configured: bool
    api_key_configured: bool
    checked_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    deployments: dict[str, AzureDeploymentCapability] = Field(default_factory=dict)
    embedding_deployment: AzureDeploymentCapability
    request_timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    redacted: bool = True

    def redacted_manifest(self) -> dict[str, Any]:
        """Return a JSON-safe redacted provider manifest."""

        payload = redact_secrets(self.model_dump(mode="json"))
        payload["api_key_configured"] = self.api_key_configured
        return cast(dict[str, Any], payload)


class AzureOpenAIReasoningClient:
    """Azure OpenAI reasoning client with strict structured-output helpers."""

    prompt_version = PROMPT_VERSION

    def __init__(self, settings: Settings | None = None, *, client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.router = AzureDeploymentRouter(self.settings)
        self.model = self.settings.azure_openai_generation_deployment
        self.api_style = self.settings.azure_openai_reasoning_api_style
        self._client = client
        self._last_response_metadata: dict[str, Any] = {}

    async def route_intent(
        self,
        request: str,
        *,
        defaults: dict[str, Any] | None = None,
    ) -> TaskIntent:
        return await self._structured(
            instructions=INTENT_ROUTER_PROMPT,
            payload={"request": request, "defaults": defaults or {}},
            schema=TaskIntent,
            schema_name="task_intent",
            task_name="task_intent",
            max_output_tokens=self.settings.reasoning_reranking_max_output_tokens,
        )

    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: type[T],
        generation_config: GenerationConfig,
    ) -> T:
        return await self._structured(
            instructions=prompt,
            payload={"task": generation_config.task_name},
            schema=schema,
            schema_name=generation_config.task_name,
            task_name=generation_config.task_name,
            max_output_tokens=generation_config.max_output_tokens,
        )

    async def plan_workflow(self, intent: TaskIntent) -> WorkflowPlan:
        return await self._structured(
            instructions=WORKFLOW_PLANNER_PROMPT,
            payload={"intent": intent.model_dump(mode="json")},
            schema=WorkflowPlan,
            schema_name="workflow_plan",
            task_name="workflow_plan",
            max_output_tokens=self.settings.reasoning_analysis_max_output_tokens,
        )

    async def synthesize_answer(
        self,
        question: str,
        evidence: EvidenceBundle,
    ) -> GroundedAnswer:
        return await self._structured(
            instructions=ANSWER_SYNTHESIS_PROMPT,
            payload={"question": question, "evidence": evidence.model_dump(mode="json")},
            schema=GroundedAnswer,
            schema_name="grounded_answer",
            task_name="answer_synthesis",
            max_output_tokens=self.settings.reasoning_answer_max_output_tokens,
        )

    async def write_user_stories(self, evidence: EvidenceBundle) -> GeneratedUserStoryBatch:
        result = await self._structured(
            instructions=USER_STORY_PROMPT,
            payload={"evidence": evidence.model_dump(mode="json")},
            schema=LLMGeneratedUserStoryBatch,
            schema_name="generated_user_story_batch",
            task_name="user_story_generation",
            max_output_tokens=self.settings.reasoning_generation_max_output_tokens,
        )
        return result.to_domain()

    async def validate_user_story(
        self,
        story: GeneratedUserStory,
        evidence: EvidenceBundle,
    ) -> QualityValidationReport:
        result = await self._structured(
            instructions=QUALITY_VALIDATION_PROMPT,
            payload={
                "story": story.model_dump(mode="json"),
                "evidence": evidence.model_dump(mode="json"),
            },
            schema=LLMQualityValidationReport,
            schema_name="quality_validation_report",
            task_name="story_validation",
            max_output_tokens=self.settings.reasoning_validation_max_output_tokens,
        )
        return result.to_domain()

    async def review_facts(
        self,
        *,
        chunk_text: str,
        facts: list[dict[str, Any]],
    ) -> FactEnrichmentBatch:
        return await self._structured(
            instructions=FACT_ENRICHMENT_PROMPT,
            payload={"chunk_text": chunk_text, "facts": facts},
            schema=FactEnrichmentBatch,
            schema_name="fact_enrichment_batch",
            task_name="fact_review",
            max_output_tokens=self.settings.reasoning_fact_review_max_output_tokens,
        )

    async def analyze_requirement_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._structured_dict(
            instructions="Analyze requirement group cohesion without inventing requirements.",
            payload=payload,
            task_name="requirement_group_analysis",
            max_output_tokens=self.settings.reasoning_analysis_max_output_tokens,
        )

    async def assess_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._structured_dict(
            instructions="Assess evidence sufficiency for grounded GraphRAG generation.",
            payload=payload,
            task_name="evidence_assessment",
            max_output_tokens=self.settings.reasoning_validation_max_output_tokens,
        )

    async def plan_retrieval(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._structured_dict(
            instructions="Plan lexical, semantic, structured-fact and graph retrieval.",
            payload=payload,
            task_name="query_planning",
            max_output_tokens=self.settings.reasoning_validation_max_output_tokens,
        )

    async def _structured_dict(
        self,
        *,
        instructions: str,
        payload: dict[str, Any],
        task_name: str,
        max_output_tokens: int,
    ) -> dict[str, Any]:
        raw = await asyncio.to_thread(
            self._create_response,
            instructions,
            payload,
            BaseModel,
            task_name,
            task_name,
            max_output_tokens,
            False,
        )
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise StructuredGenerationError(f"Azure task {task_name} did not return an object.")
        return parsed

    async def _structured(
        self,
        *,
        instructions: str,
        payload: dict[str, Any],
        schema: type[T],
        schema_name: str,
        task_name: str,
        max_output_tokens: int,
    ) -> T:
        raw = await asyncio.to_thread(
            self._create_response,
            instructions,
            payload,
            schema,
            schema_name,
            task_name,
            max_output_tokens,
            True,
        )
        try:
            return schema.model_validate_json(raw)
        except ValidationError as exc:
            raise StructuredGenerationError(
                f"Azure structured output failed validation for {schema_name}: {exc}"
            ) from exc

    def _create_response(
        self,
        instructions: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        schema_name: str,
        task_name: str,
        max_output_tokens: int,
        strict_schema: bool,
    ) -> str:
        deployment = self.router.deployment_for_task(task_name)
        started = time.perf_counter()
        client = self._get_client()
        try:
            if self.api_style == "responses":
                response = client.responses.create(
                    model=deployment,
                    instructions=instructions,
                    input=json.dumps(payload, ensure_ascii=False),
                    max_output_tokens=max_output_tokens,
                    store=self.settings.reasoning_store_responses,
                    text=_response_text_format(schema, schema_name, strict_schema),
                )
            elif self.api_style == "chat_completions":
                chat_kwargs: dict[str, Any] = {
                    "model": deployment,
                    "messages": [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    "response_format": _chat_response_format(schema, schema_name, strict_schema),
                    **_chat_token_kwargs(deployment, max_output_tokens),
                }
                temperature = _chat_temperature_kwargs(
                    deployment,
                    self.settings.reasoning_temperature,
                )
                if temperature is not None:
                    chat_kwargs.update(temperature)
                response = client.chat.completions.create(**chat_kwargs)
            else:
                raise ConfigError(
                    "AZURE_OPENAI_REASONING_API_STYLE must be chat_completions or responses."
                )
        except (GenerationTokenLimitError, ProviderCapabilityError, StructuredGenerationError):
            raise
        except Exception as exc:
            raise StructuredGenerationError(
                _provider_error_message(
                    provider="azure_openai",
                    deployment=deployment,
                    api_style=self.api_style,
                    operation=schema_name,
                    exc=exc,
                )
            ) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        finish_reason = _response_finish_reason(response)
        self._last_response_metadata = redact_secrets(
            {
                "deployment": deployment,
                "task_name": task_name,
                "schema_name": schema_name,
                "api_style": self.api_style,
                "duration_ms": duration_ms,
                "finish_reason": finish_reason,
                "request_id": _response_request_id(response),
                "usage": _response_usage(response),
                "requested_max_output_tokens": max_output_tokens,
            }
        )
        if finish_reason and finish_reason.lower() in {"length", "max_tokens"}:
            raise GenerationTokenLimitError(
                f"Azure OpenAI response for {schema_name} was truncated "
                f"(finish_reason={finish_reason})."
            )
        output_text = _response_output_text(response)
        if not output_text and self.settings.reasoning_fail_on_empty_output:
            raise StructuredGenerationError(
                f"Azure OpenAI returned empty structured output for {schema_name}."
            )
        return output_text

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        self._client = build_azure_openai_client(self.settings)
        return self._client


def azure_preflight(
    settings: Settings,
    *,
    deployment_capabilities: Mapping[str, AzureDeploymentCapability] | None = None,
) -> AzureOpenAICapabilityManifest:
    """Validate static Azure configuration and return a redacted manifest."""

    endpoint = settings.azure_openai_endpoint
    if not endpoint:
        raise ConfigError("AZURE_OPENAI_ENDPOINT is required for Azure OpenAI workflows.")
    normalized_endpoint = normalize_azure_endpoint(endpoint)
    if settings.azure_openai_base_url:
        raise ConfigError(
            "azure_openai.base_url is deprecated for native Azure OpenAI providers; "
            "set AZURE_OPENAI_ENDPOINT instead."
        )

    deployments = {
        "generation": settings.azure_openai_generation_deployment,
        "answer": settings.azure_openai_answer_deployment,
        "analysis": settings.azure_openai_analysis_deployment,
        "utility": settings.azure_openai_utility_deployment,
        "validation": settings.azure_openai_validation_deployment,
        "reranker": settings.azure_openai_reranker_deployment,
    }
    capability_records: dict[str, AzureDeploymentCapability] = {}
    for name, deployment in deployments.items():
        _validate_deployment_name(deployment)
        record = deployment_capabilities.get(deployment) if deployment_capabilities else None
        capability_records[name] = record or AzureDeploymentCapability(
            deployment=deployment,
            reachable=False,
            api_style=settings.azure_openai_reasoning_api_style,
            structured_output=False,
        )
    embedding_deployment = settings.azure_openai_embedding_deployment
    _validate_deployment_name(embedding_deployment, embedding=True)
    embedding_record = (
        deployment_capabilities.get(embedding_deployment) if deployment_capabilities else None
    ) or AzureDeploymentCapability(deployment=embedding_deployment, reachable=False)
    _validate_requested_output_budgets(settings, capability_records)
    return AzureOpenAICapabilityManifest(
        endpoint=normalized_endpoint,
        reasoning_api_style=settings.azure_openai_reasoning_api_style,
        api_version_configured=bool(settings.azure_openai_api_version),
        api_key_configured=bool(settings.azure_openai_api_key),
        deployments=capability_records,
        embedding_deployment=embedding_record,
        request_timeout_seconds=settings.azure_openai_request_timeout_seconds,
        max_retries=settings.azure_openai_max_retries,
        retry_backoff_seconds=settings.azure_openai_retry_backoff_seconds,
    )


def _validate_deployment_name(deployment: str, *, embedding: bool = False) -> None:
    if not deployment.strip():
        if embedding:
            raise ConfigError("Azure OpenAI embeddings require a deployment name.")
        raise ConfigError("Azure OpenAI reasoning requires a deployment name.")
    if deployment == "gpt-5.3-codex":
        raise ConfigError("gpt-5.3-codex is not allowed for BRD reasoning tasks.")
    if embedding and deployment == "text-embedding-ada-002":
        raise ConfigError("text-embedding-ada-002 is not allowed for new indexing.")


def _validate_requested_output_budgets(
    settings: Settings,
    records: Mapping[str, AzureDeploymentCapability],
) -> None:
    task_budgets = {
        "analysis": settings.reasoning_analysis_max_output_tokens,
        "generation": settings.reasoning_generation_max_output_tokens,
        "validation": settings.reasoning_validation_max_output_tokens,
        "answer": settings.reasoning_answer_max_output_tokens,
        "utility": max(
            settings.reasoning_fact_review_max_output_tokens,
            settings.reasoning_reranking_max_output_tokens,
        ),
    }
    for task, requested in task_budgets.items():
        record = records.get(task)
        if record is None or record.max_output_tokens is None:
            continue
        if requested > record.max_output_tokens:
            raise ProviderCapabilityError(
                f"Configured {task} output budget {requested} exceeds deployment "
                f"{record.deployment} capability {record.max_output_tokens}."
            )


def _response_text_format(
    schema: type[BaseModel],
    schema_name: str,
    strict_schema: bool,
) -> dict[str, Any] | None:
    if not strict_schema:
        return {"format": {"type": "json_object"}}
    return {
        "format": {
            "type": "json_schema",
            "name": schema_name,
            "schema": strict_openai_schema(schema),
            "strict": True,
        }
    }


def _chat_response_format(
    schema: type[BaseModel],
    schema_name: str,
    strict_schema: bool,
) -> dict[str, Any] | None:
    if not strict_schema:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "schema": strict_openai_schema(schema),
            "strict": True,
        },
    }


def _chat_token_kwargs(deployment: str, max_output_tokens: int) -> dict[str, int]:
    if _is_gpt5_deployment(deployment):
        return {"max_completion_tokens": max_output_tokens}
    return {"max_tokens": max_output_tokens}


def _chat_temperature_kwargs(deployment: str, temperature: float) -> dict[str, float] | None:
    if _is_gpt5_deployment(deployment):
        return None
    return {"temperature": temperature}


def _is_gpt5_deployment(deployment: str) -> bool:
    lowered = deployment.strip().lower()
    return lowered.startswith("gpt-5")


def _response_output_text(response: Any) -> str:
    helper = getattr(response, "output_text", None)
    if isinstance(helper, str) and helper.strip():
        return helper
    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if content:
            return str(content)
    output = getattr(response, "output", None)
    if not output:
        return ""
    parts: list[str] = []
    for item in output:
        content = getattr(item, "content", None)
        if not content and isinstance(item, dict):
            content = item.get("content")
        if not content:
            continue
        for content_item in content:
            text = getattr(content_item, "text", None)
            if text is None and isinstance(content_item, dict):
                text = content_item.get("text")
            if text:
                parts.append(str(text))
    return "".join(parts)


def _response_finish_reason(response: Any) -> str | None:
    choices = getattr(response, "choices", None)
    if choices:
        reason = getattr(choices[0], "finish_reason", None)
        if reason:
            return str(reason)
    status = getattr(response, "status", None)
    if status == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None)
        return str(reason or "length")
    return None


def _response_request_id(response: Any) -> str | None:
    for attr in ("_request_id", "request_id", "id"):
        value = getattr(response, attr, None)
        if value:
            return str(value)
    return None


def _response_usage(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return cast(dict[str, Any], usage.model_dump(mode="json"))
    if isinstance(usage, dict):
        return cast(dict[str, Any], usage)
    return {
        name: getattr(usage, name)
        for name in ("input_tokens", "output_tokens", "total_tokens")
        if getattr(usage, name, None) is not None
    }


def _provider_error_message(
    *,
    provider: str,
    deployment: str,
    api_style: str,
    operation: str,
    exc: Exception,
) -> str:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    code = getattr(exc, "code", None)
    request_id = getattr(exc, "request_id", None)
    headers = getattr(response, "headers", None)
    if request_id is None and isinstance(headers, Mapping):
        request_id = headers.get("x-request-id") or headers.get("x-ms-request-id")
    parts = [
        f"{provider} request failed for {operation}",
        f"deployment={deployment}",
        f"api_style={api_style}",
    ]
    if status_code is not None:
        parts.append(f"status_code={status_code}")
    if code:
        parts.append(f"azure_error_code={code}")
    if request_id:
        parts.append(f"request_id={request_id}")
    parts.append(f"detail={exc}")
    return "; ".join(parts)
