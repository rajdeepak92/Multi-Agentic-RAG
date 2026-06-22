"""Optional Gemini structured-reasoning client."""

from __future__ import annotations

import asyncio
import json
from importlib import import_module
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from multi_agentic_rag.config import Settings
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
    QUALITY_VALIDATION_PROMPT,
    USER_STORY_PROMPT,
    WORKFLOW_PLANNER_PROMPT,
)
from multi_agentic_rag.llm.structured import GenerationConfig, extract_json_object

T = TypeVar("T", bound=BaseModel)


class GeminiReasoningClient:
    """Gemini provider placeholder with dependency and key preflight."""

    prompt_version = "gemini-structured-v1"

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        if not settings.gemini_api_key:
            raise ConfigError("GEMINI_API_KEY is required for `--model gemini`.")
        if client is None:
            try:
                module = import_module("google.genai")
            except ModuleNotFoundError as exc:
                raise ConfigError(
                    "Gemini support requires the optional `gemini` dependency. "
                    "Run `uv sync --extra gemini` or install `qa-automation-agents[gemini]`."
                ) from exc
            client = module.Client(api_key=settings.gemini_api_key)
        self.settings = settings
        self.client = client
        self.model = settings.gemini_reasoning_model

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
        return await self._structured(
            instructions=ANSWER_SYNTHESIS_PROMPT,
            payload={"question": question, "evidence": evidence.model_dump(mode="json")},
            schema=GroundedAnswer,
            schema_name="grounded_answer",
        )

    async def write_user_stories(self, evidence: EvidenceBundle) -> GeneratedUserStoryBatch:
        return await self._structured(
            instructions=USER_STORY_PROMPT,
            payload={"evidence": evidence.model_dump(mode="json")},
            schema=GeneratedUserStoryBatch,
            schema_name="generated_user_story_batch",
        )

    async def validate_user_story(
        self,
        story: GeneratedUserStory,
        evidence: EvidenceBundle,
    ) -> QualityValidationReport:
        return await self._structured(
            instructions=QUALITY_VALIDATION_PROMPT,
            payload={
                "story": story.model_dump(mode="json"),
                "evidence": evidence.model_dump(mode="json"),
            },
            schema=QualityValidationReport,
            schema_name="quality_validation_report",
        )

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
        )

    async def _structured(
        self,
        *,
        instructions: str,
        payload: dict[str, Any],
        schema: type[T],
        schema_name: str,
    ) -> T:
        raw = await asyncio.to_thread(
            self._generate_text,
            instructions,
            payload,
            schema,
            schema_name,
        )
        try:
            return schema.model_validate(extract_json_object(raw))
        except (ValueError, ValidationError) as exc:
            raise MultiAgenticRagError(
                f"Gemini structured output failed validation for {schema_name}: {exc}"
            ) from exc

    def _generate_text(
        self,
        instructions: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        schema_name: str,
    ) -> str:
        contents = (
            f"{instructions}\n\n"
            f"Return JSON matching this schema name: {schema_name}.\n"
            f"JSON Schema:\n{json.dumps(schema.model_json_schema(), ensure_ascii=False)}\n\n"
            f"Payload:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config={"response_mime_type": "application/json"},
            )
        except Exception as exc:
            raise MultiAgenticRagError(f"Gemini request failed for {schema_name}: {exc}") from exc
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text
        raise MultiAgenticRagError(f"Gemini returned no structured text for {schema_name}.")
