"""OpenAI Responses API wrapper for structured reasoning calls."""

from __future__ import annotations

import asyncio
import json
from importlib import import_module
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

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
from multi_agentic_rag.exceptions import ConfigError, MultiAgenticRagError
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
    ReasoningClient,
    strict_openai_schema,
)

T = TypeVar("T", bound=BaseModel)

__all__ = ["OpenAIReasoningClient", "ReasoningClient", "strict_openai_schema"]


class OpenAIReasoningClient:
    """Responses API client with structured-output helpers."""

    prompt_version = PROMPT_VERSION

    def __init__(self, settings: Settings | None = None, *, client: Any | None = None) -> None:
        """Create a reasoning client.

        Args:
            settings: Runtime settings. When omitted, environment settings are loaded.
            client: Optional already-created OpenAI-compatible client for tests.
        """

        self.settings = settings or get_settings()
        self.model = self.settings.openai_reasoning_model
        self.reasoning_effort = self.settings.openai_reasoning_effort
        self.store = self.settings.openai_store_responses
        self._client = client

    async def route_intent(
        self,
        request: str,
        *,
        defaults: dict[str, Any] | None = None,
    ) -> TaskIntent:
        """Classify a natural-language task into a structured intent."""

        return await self._structured(
            instructions=INTENT_ROUTER_PROMPT,
            payload={
                "request": request,
                "defaults": defaults or {},
            },
            schema=TaskIntent,
            schema_name="task_intent",
        )

    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: type[T],
        generation_config: GenerationConfig,
    ) -> T:
        """Generate typed structured output for LangGraph reasoning nodes."""

        return await self._structured(
            instructions=prompt,
            payload={"task": generation_config.task_name},
            schema=schema,
            schema_name=generation_config.task_name,
        )

    async def plan_workflow(self, intent: TaskIntent) -> WorkflowPlan:
        """Create a workflow plan from an intent."""

        return await self._structured(
            instructions=WORKFLOW_PLANNER_PROMPT,
            payload={"intent": intent.model_dump(mode="json")},
            schema=WorkflowPlan,
            schema_name="workflow_plan",
        )

    async def synthesize_answer(
        self,
        question: str,
        evidence: EvidenceBundle,
    ) -> GroundedAnswer:
        """Create a concise answer from validated evidence only."""

        return await self._structured(
            instructions=ANSWER_SYNTHESIS_PROMPT,
            payload={
                "question": question,
                "evidence": evidence.model_dump(mode="json"),
            },
            schema=GroundedAnswer,
            schema_name="grounded_answer",
        )

    async def write_user_stories(
        self,
        evidence: EvidenceBundle,
    ) -> GeneratedUserStoryBatch:
        """Generate user stories from validated evidence."""

        result = await self._structured(
            instructions=USER_STORY_PROMPT,
            payload={"evidence": evidence.model_dump(mode="json")},
            schema=LLMGeneratedUserStoryBatch,
            schema_name="generated_user_story_batch",
            reasoning_effort="high",
        )
        return result.to_domain()

    async def validate_user_story(
        self,
        story: GeneratedUserStory,
        evidence: EvidenceBundle,
    ) -> QualityValidationReport:
        """Validate a user story against the supplied evidence bundle."""

        result = await self._structured(
            instructions=QUALITY_VALIDATION_PROMPT,
            payload={
                "story": story.model_dump(mode="json"),
                "evidence": evidence.model_dump(mode="json"),
            },
            schema=LLMQualityValidationReport,
            schema_name="quality_validation_report",
        )
        return result.to_domain()

    async def review_facts(
        self,
        *,
        chunk_text: str,
        facts: list[dict[str, Any]],
    ) -> FactEnrichmentBatch:
        """Review ambiguous extracted facts without changing the canonical set."""

        return await self._structured(
            instructions=FACT_ENRICHMENT_PROMPT,
            payload={
                "chunk_text": chunk_text,
                "facts": facts,
            },
            schema=FactEnrichmentBatch,
            schema_name="fact_enrichment_batch",
        )

    async def _structured(
        self,
        *,
        instructions: str,
        payload: dict[str, Any],
        schema: type[T],
        schema_name: str,
        reasoning_effort: str | None = None,
    ) -> T:
        raw = await asyncio.to_thread(
            self._create_response,
            instructions,
            payload,
            schema,
            schema_name,
            reasoning_effort,
        )
        try:
            return schema.model_validate_json(raw)
        except ValidationError as exc:
            raise MultiAgenticRagError(
                f"OpenAI structured output failed validation for {schema_name}: {exc}"
            ) from exc

    def _create_response(
        self,
        instructions: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        schema_name: str,
        reasoning_effort: str | None,
    ) -> str:
        client = self._get_client()
        try:
            response = client.responses.create(
                model=self.model,
                instructions=instructions,
                input=json.dumps(payload, ensure_ascii=False),
                reasoning={"effort": reasoning_effort or self.reasoning_effort},
                store=self.store,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": strict_openai_schema(schema),
                        "strict": True,
                    }
                },
            )
        except MultiAgenticRagError:
            raise
        except Exception as exc:
            raise MultiAgenticRagError(
                f"OpenAI request failed for {schema_name}: {_openai_exception_detail(exc)}"
            ) from exc
        output_text = _response_output_text(response)
        if not output_text:
            raise MultiAgenticRagError(f"OpenAI returned no structured text for {schema_name}.")
        return output_text

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.settings.openai_api_key:
            raise ConfigError("OPENAI_API_KEY is required for OpenAI reasoning workflows.")
        module = import_module("openai")
        self._client = module.OpenAI(api_key=self.settings.openai_api_key)
        return self._client


def _response_output_text(response: Any) -> str:
    helper = getattr(response, "output_text", None)
    if isinstance(helper, str) and helper.strip():
        return helper
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


def _openai_exception_detail(exc: Exception) -> str:
    parts = [str(exc)]
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    code = getattr(exc, "code", None)
    body = getattr(exc, "body", None)
    if code is None and isinstance(body, dict):
        body_error = body.get("error")
        code = body_error.get("code") if isinstance(body_error, dict) else body.get("code")
    if status_code is not None and f"{status_code}" not in parts[0]:
        parts.append(f"HTTP {status_code}")
    if code and str(code) not in parts[0]:
        parts.append(str(code))
    return "; ".join(part for part in parts if part)
