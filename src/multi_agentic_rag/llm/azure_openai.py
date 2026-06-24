"""Azure OpenAI provider integration with task-specific deployment routing."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from typing import Any, TypeVar, cast
from urllib.parse import urlparse

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
    endpoint: str
    base_url: str | None = None
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
            if hasattr(client, "responses"):
                response = client.responses.create(
                    model=deployment,
                    instructions=instructions,
                    input=json.dumps(payload, ensure_ascii=False),
                    temperature=self.settings.reasoning_temperature,
                    max_output_tokens=max_output_tokens,
                    store=self.settings.reasoning_store_responses,
                    text=_response_text_format(schema, schema_name, strict_schema),
                )
            elif hasattr(client, "chat"):
                response = client.chat.completions.create(
                    model=deployment,
                    messages=[
                        {"role": "system", "content": instructions},
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    ],
                    temperature=self.settings.reasoning_temperature,
                    max_tokens=max_output_tokens,
                    response_format=_chat_response_format(schema, schema_name, strict_schema),
                )
            else:
                raise ProviderCapabilityError(
                    "Azure OpenAI client supports neither Responses nor Chat Completions."
                )
        except (GenerationTokenLimitError, ProviderCapabilityError, StructuredGenerationError):
            raise
        except Exception as exc:
            raise StructuredGenerationError(
                f"Azure OpenAI request failed for {schema_name}: {_provider_exception_detail(exc)}"
            ) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        finish_reason = _response_finish_reason(response)
        self._last_response_metadata = redact_secrets(
            {
                "deployment": deployment,
                "task_name": task_name,
                "schema_name": schema_name,
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
        endpoint = self.settings.azure_openai_endpoint
        base_url = self.settings.azure_openai_base_url
        api_key = self.settings.azure_openai_api_key
        if not api_key:
            raise ConfigError("AZURE_OPENAI_API_KEY is required for Azure OpenAI workflows.")
        module = import_module("openai")
        if base_url:
            self._client = module.OpenAI(
                api_key=api_key,
                base_url=normalize_azure_endpoint(base_url, allow_base_url=True),
                timeout=self.settings.azure_openai_request_timeout_seconds,
                max_retries=self.settings.azure_openai_max_retries,
            )
        else:
            if not endpoint:
                raise ConfigError("AZURE_OPENAI_ENDPOINT is required for Azure OpenAI workflows.")
            if not self.settings.azure_openai_api_version:
                raise ConfigError(
                    "AZURE_OPENAI_API_VERSION is required when using AzureOpenAI client."
                )
            self._client = module.AzureOpenAI(
                api_key=api_key,
                azure_endpoint=normalize_azure_endpoint(endpoint),
                api_version=self.settings.azure_openai_api_version,
                timeout=self.settings.azure_openai_request_timeout_seconds,
                max_retries=self.settings.azure_openai_max_retries,
            )
        return self._client


def azure_preflight(
    settings: Settings,
    *,
    deployment_capabilities: Mapping[str, AzureDeploymentCapability] | None = None,
) -> AzureOpenAICapabilityManifest:
    """Validate static Azure configuration and return a redacted manifest.

    Live reachability is intentionally injected through ``deployment_capabilities`` so
    tests can validate behavior without network calls.
    """

    endpoint = settings.azure_openai_endpoint or settings.azure_openai_base_url
    if not endpoint:
        raise ConfigError("Azure OpenAI endpoint or base_url is required.")
    normalized_endpoint = normalize_azure_endpoint(
        endpoint,
        allow_base_url=bool(settings.azure_openai_base_url),
    )
    if not settings.azure_openai_api_key:
        raise ConfigError("AZURE_OPENAI_API_KEY is required; it will not be printed.")
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
        record = (
            deployment_capabilities.get(deployment)
            if deployment_capabilities is not None
            else None
        )
        capability_records[name] = record or AzureDeploymentCapability(
            deployment=deployment,
            reachable=False,
            api_style="unverified",
            structured_output=False,
        )
    embedding_deployment = settings.azure_openai_embedding_deployment
    _validate_deployment_name(embedding_deployment, embedding=True)
    embedding_record = (
        deployment_capabilities.get(embedding_deployment)
        if deployment_capabilities is not None
        else None
    ) or AzureDeploymentCapability(deployment=embedding_deployment, reachable=False)
    _validate_requested_output_budgets(settings, capability_records)
    return AzureOpenAICapabilityManifest(
        endpoint=normalized_endpoint,
        base_url=settings.azure_openai_base_url,
        api_version_configured=bool(settings.azure_openai_api_version),
        api_key_configured=bool(settings.azure_openai_api_key),
        deployments=capability_records,
        embedding_deployment=embedding_record,
        request_timeout_seconds=settings.azure_openai_request_timeout_seconds,
        max_retries=settings.azure_openai_max_retries,
        retry_backoff_seconds=settings.azure_openai_retry_backoff_seconds,
    )


def normalize_azure_endpoint(endpoint: str, *, allow_base_url: bool = False) -> str:
    """Normalize and validate a complete HTTPS Azure OpenAI endpoint."""

    stripped = endpoint.strip()
    parsed = urlparse(stripped)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError("Azure OpenAI endpoint must be a complete HTTPS URL.")
    if allow_base_url and "/openai/" not in parsed.path:
        raise ConfigError("Azure OpenAI base_url must include the /openai/ API path.")
    return stripped.rstrip("/") + ("/" if allow_base_url and not stripped.endswith("/") else "")


def _validate_deployment_name(deployment: str, *, embedding: bool = False) -> None:
    if not deployment.strip():
        raise ConfigError("Azure OpenAI deployment names must not be empty.")
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
        return None
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


def _provider_exception_detail(exc: Exception) -> str:
    parts = [str(exc)]
    for attr in ("status_code", "code", "request_id"):
        value = getattr(exc, attr, None)
        if value is not None and str(value) not in parts[0]:
            parts.append(str(value))
    return "; ".join(part for part in parts if part)
