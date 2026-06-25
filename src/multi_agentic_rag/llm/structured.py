"""Shared structured reasoning contracts and JSON helpers."""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Protocol, TypeVar, cast

from pydantic import BaseModel, Field

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

T = TypeVar("T", bound=BaseModel)


class ReasoningClient(Protocol):
    """Structured reasoning operations used by high-level agents."""

    model: str
    prompt_version: str

    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: type[T],
        generation_config: GenerationConfig,
    ) -> T:
        """Generate one typed structured object from a prompt."""

    async def route_intent(
        self,
        request: str,
        *,
        defaults: dict[str, Any] | None = None,
    ) -> TaskIntent:
        """Classify a natural-language task."""

    async def plan_workflow(self, intent: TaskIntent) -> WorkflowPlan:
        """Create an ordered high-level workflow plan."""

    async def synthesize_answer(
        self,
        question: str,
        evidence: EvidenceBundle,
    ) -> GroundedAnswer:
        """Synthesize an evidence-grounded answer."""

    async def write_user_stories(
        self,
        evidence: EvidenceBundle,
    ) -> GeneratedUserStoryBatch:
        """Generate user stories from validated evidence."""

    async def validate_user_story(
        self,
        story: GeneratedUserStory,
        evidence: EvidenceBundle,
    ) -> QualityValidationReport:
        """Validate a generated user story against evidence."""

    async def review_facts(
        self,
        *,
        chunk_text: str,
        facts: list[dict[str, Any]],
    ) -> FactEnrichmentBatch:
        """Review ambiguous facts without replacing the canonical set."""


class LLMClaimTraceability(BaseModel):
    """Traceability for one generated story claim."""

    claim_type: Literal[
        "user_story",
        "business_value",
        "description",
        "acceptance_criterion",
        "non_functional_requirement",
        "definition_of_ready",
        "definition_of_done",
    ]
    claim_index: int | None = None
    claim_text: str
    requirement_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    evidence_paths: list[list[str]] = Field(default_factory=list)


class LLMTraceability(BaseModel):
    """Closed traceability object used by reasoning structured-output DTOs."""

    chunk_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    evidence_paths: list[list[str]] = Field(default_factory=list)
    claims: list[LLMClaimTraceability] = Field(default_factory=list)

    def to_domain(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class GenerationConfig(BaseModel):
    """Provider-neutral generation controls for graph reasoning nodes."""

    temperature: float = 0.1
    max_output_tokens: int = 2048
    retry_count: int = 1
    task_name: str = "structured_reasoning"


class LLMGeneratedUserStory(BaseModel):
    """Closed DTO for generated user-story output."""

    id: str
    title: str
    type: str
    domain: str
    priority: str
    status: str
    persona: str
    user_story: str
    business_value: str
    description: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    non_functional_requirements: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    definition_of_ready: list[str] = Field(default_factory=list)
    definition_of_done: list[str] = Field(default_factory=list)
    traceability: LLMTraceability = Field(default_factory=LLMTraceability)

    def to_domain(self) -> GeneratedUserStory:
        payload = self.model_dump(mode="json")
        payload["traceability"] = self.traceability.to_domain()
        return GeneratedUserStory.model_validate(payload)


class LLMGeneratedUserStoryBatch(BaseModel):
    """Closed DTO for user-story batches."""

    stories: list[LLMGeneratedUserStory] = Field(default_factory=list)
    reasoning_summary: str = ""

    def to_domain(self) -> GeneratedUserStoryBatch:
        return GeneratedUserStoryBatch(
            stories=[story.to_domain() for story in self.stories],
            reasoning_summary=self.reasoning_summary,
        )


class LLMUserStoryEvidence(BaseModel):
    """Compact evidence row used by the user-story prompt."""

    chunk_id: str
    rank: int
    source_name: str
    page: int
    evidence_path: list[str] = Field(default_factory=list)
    score: float
    excerpt: str


class LLMUserStoryPrompt(BaseModel):
    """Compact prompt payload shared by generation and validation."""

    query: str
    version_scope: str | None = None
    story: LLMGeneratedUserStory | None = None
    evidence: list[LLMUserStoryEvidence] = Field(default_factory=list)


class LLMQualityChecks(BaseModel):
    """Closed validation checks used by reasoning structured-output DTOs."""

    evidence_traceable: bool = False
    citations_supported: bool = False
    schema_complete: bool = False
    unsupported_claims_absent: bool = False

    def to_domain(self) -> dict[str, bool]:
        return self.model_dump(mode="json")


class LLMQualityValidationReport(BaseModel):
    """Closed DTO for validation reports."""

    status: Literal["passed", "failed"]
    messages: list[str] = Field(default_factory=list)
    checks: LLMQualityChecks = Field(default_factory=LLMQualityChecks)

    def to_domain(self) -> QualityValidationReport:
        return QualityValidationReport(
            status=self.status,
            messages=self.messages,
            checks=self.checks.to_domain(),
        )


def strict_openai_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Return an OpenAI strict-mode-compatible JSON schema for a Pydantic model."""

    raw_schema = schema.model_json_schema()
    return cast(dict[str, Any], _close_json_schema(raw_schema))


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response."""

    cleaned = clean_model_json_text(text)
    decoder = json.JSONDecoder()
    for index, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return cast(dict[str, Any], candidate)
    raise ValueError("No JSON object found in model output.")


def clean_model_json_text(text: str) -> str:
    """Remove common non-JSON wrappers around local model output."""

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return cleaned


def _close_json_schema(node: Any) -> Any:
    if isinstance(node, list):
        return [_close_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node

    closed: dict[str, Any] = {}
    for key, value in node.items():
        if key in {"default", "examples"}:
            continue
        if key in {"properties", "$defs", "definitions"} and isinstance(value, dict):
            closed[key] = {
                str(child_key): _close_json_schema(child) for child_key, child in value.items()
            }
            continue
        if key in {"items", "anyOf", "allOf", "oneOf", "not"}:
            closed[key] = _close_json_schema(value)
            continue
        if key == "additionalProperties":
            continue
        closed[key] = _close_json_schema(value)

    properties = closed.get("properties")
    node_type = closed.get("type")
    is_object = node_type == "object" or isinstance(properties, dict)
    if is_object:
        if not isinstance(properties, dict):
            properties = {}
            closed["properties"] = properties
        closed["additionalProperties"] = False
        closed["required"] = list(properties.keys())
    return closed
