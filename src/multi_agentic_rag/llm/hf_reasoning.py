"""Local Hugging Face Transformers reasoning client."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, TypeVar, cast

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
    LLMGeneratedUserStory,
    LLMGeneratedUserStoryBatch,
    LLMQualityValidationReport,
    LLMUserStoryEvidence,
    LLMUserStoryPrompt,
    extract_json_object,
)

T = TypeVar("T", bound=BaseModel)

HF_REASONING_INSTALL_HINT = (
    "Hugging Face reasoning requires optional dependencies. "
    "Install them with `uv sync --dev --extra hf-reasoning --extra cpu --link-mode=copy` "
    "for CPU or `uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy` "
    "for NVIDIA GPU, then run HF commands with `uv run --no-sync`."
)
HF_REASONING_GPU_INSTALL_HINT = (
    "For NVIDIA GPU support, install CUDA PyTorch with "
    "`uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy`."
)
HF_REASONING_GPU_INSTALL_COMMAND = (
    "uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy"
)
HF_BASE_DEPENDENCIES = ("transformers", "torch", "safetensors")
HF_AUTO_DEVICE_DEPENDENCY = "accelerate"
USER_STORY_EVIDENCE_EXCERPT_TOKENS = 256
PROMPT_RESERVED_TOKENS = 2048
DEFAULT_MODEL_WINDOW = 40960
USER_STORY_SCHEMA_NAMES = {
    "generated_user_story_batch",
    "quality_validation_report",
}
THRESHOLD_COLUMNS = (
    ("normal_range", "Normal range"),
    ("min", "Minimum threshold"),
    ("max", "Maximum threshold"),
    ("critical", "Critical level"),
)
THRESHOLD_FIELD_TERMS = {
    "normal_range": {"normal", "range", "average", "baseline", "operating"},
    "min": {"min", "minimum", "low", "lower"},
    "max": {"max", "maximum", "high", "upper"},
    "critical": {"critical", "danger", "severe"},
}
THRESHOLD_VALUE_PATTERN = re.compile(
    r"[<>]?=?\s*\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?\s*"
    r"(?:°\s*[CF]|[CF]\b|mm/s|m/s|psi|bar|%)?",
    flags=re.IGNORECASE,
)
SENSOR_ROW_PATTERN = re.compile(
    r"\b(?P<sensor>[A-Z][A-Za-z-]*\s+Sensor)\s+"
    r"(?=[<>]?\s*\d)",
)


@dataclass(frozen=True)
class HFDependencyStatus:
    """Import status for one Hugging Face reasoning dependency."""

    name: str
    installed: bool
    version: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class HFReasoningEnvironmentReport:
    """Runtime report used by HF preflight and the CLI diagnostic command."""

    model: str
    device: str
    dtype: str
    max_new_tokens: int
    validation_max_new_tokens: int
    timeout_seconds: float
    answer_mode: str
    cache_dir: Path
    token_present: bool
    fact_review_policy: str
    accelerate_required: bool
    dependencies: tuple[HFDependencyStatus, ...]
    cuda_available: bool | None
    cuda_device_count: int | None
    cuda_version: str | None
    torch_version: str | None
    torch_cuda_built: bool | None
    cuda_device_name: str | None
    nvidia_smi_available: bool
    gpu_install_command: str | None

    @property
    def missing_required_dependencies(self) -> tuple[str, ...]:
        """Return required dependency names that are not importable."""

        return tuple(
            dependency.name for dependency in self.dependencies if not dependency.installed
        )

    @property
    def dependencies_ready(self) -> bool:
        """Return whether every required dependency is importable."""

        return not self.missing_required_dependencies

    @property
    def torch_cpu_only_with_nvidia_driver(self) -> bool:
        """Return whether NVIDIA appears present but this torch build cannot use CUDA."""

        return (
            self.nvidia_smi_available
            and self.torch_version is not None
            and self.cuda_available is False
            and self.cuda_version is None
            and self.torch_cuda_built is False
        )

    @property
    def torch_build_label(self) -> str:
        """Return a human-readable summary of the active torch build."""

        if self.torch_cuda_built is True:
            return "CUDA-enabled"
        if self.torch_cuda_built is False:
            return "CPU-only"
        return "unknown"


@dataclass(frozen=True)
class ThresholdAnswerRow:
    """One threshold table row recovered from retrieved evidence."""

    sensor_label: str
    values: dict[str, str]
    chunk_id: str
    source_name: str
    page: int
    version: str


@dataclass(frozen=True)
class PromptFitResult:
    """Prompt payload and budget trace after deterministic compaction."""

    payload: dict[str, Any]
    prompt: str
    prompt_tokens: int
    model_window: int
    max_new_tokens: int
    pruned_chunk_ids: tuple[str, ...] = ()


class HuggingFaceReasoningClient:
    """In-process Transformers client using prompt-enforced JSON output."""

    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        tokenizer: Any | None = None,
        model: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model = self.settings.hf_reason_model
        self._tokenizer = tokenizer
        self._model = model

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
            max_new_tokens=generation_config.max_output_tokens,
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

        if self.settings.hf_reason_answer_mode in {"deterministic", "extractive"}:
            return _extractive_grounded_answer(question, evidence)
        try:
            return await self._structured(
                instructions=ANSWER_SYNTHESIS_PROMPT,
                payload={
                    "question": question,
                    "evidence": evidence.model_dump(mode="json"),
                },
                schema=GroundedAnswer,
                schema_name="grounded_answer",
            )
        except MultiAgenticRagError:
            return _extractive_grounded_answer(question, evidence)

    async def write_user_stories(
        self,
        evidence: EvidenceBundle,
    ) -> GeneratedUserStoryBatch:
        """Generate user stories from validated evidence."""

        payload = self._build_user_story_prompt_payload(evidence)
        result = await self._structured(
            instructions=USER_STORY_PROMPT,
            payload=payload,
            schema=LLMGeneratedUserStoryBatch,
            schema_name="generated_user_story_batch",
        )
        return result.to_domain()

    async def validate_user_story(
        self,
        story: GeneratedUserStory,
        evidence: EvidenceBundle,
    ) -> QualityValidationReport:
        """Validate a user story against the supplied evidence bundle."""

        payload = self._build_user_story_prompt_payload(evidence, story=story)
        result = await self._structured(
            instructions=QUALITY_VALIDATION_PROMPT,
            payload=payload,
            schema=LLMQualityValidationReport,
            schema_name="quality_validation_report",
            max_new_tokens=self.settings.hf_reason_validation_max_new_tokens,
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

    def _build_user_story_prompt_payload(
        self,
        evidence: EvidenceBundle,
        *,
        story: GeneratedUserStory | None = None,
    ) -> dict[str, Any]:
        """Build the compact prompt payload shared by both user-story calls."""

        prompt = LLMUserStoryPrompt(
            query=evidence.query,
            version_scope=evidence.version_scope,
            story=(
                LLMGeneratedUserStory.model_validate(story.model_dump(mode="json"))
                if story is not None
                else None
            ),
            evidence=self._build_user_story_prompt_evidence(evidence),
        )
        return prompt.model_dump(mode="json")

    def _build_user_story_prompt_evidence(
        self,
        evidence: EvidenceBundle,
    ) -> list[LLMUserStoryEvidence]:
        """Build compact, traceable evidence rows for user-story prompting."""

        return [
            LLMUserStoryEvidence(
                chunk_id=result.chunk_id,
                rank=result.rank,
                source_name=result.source_name,
                page=result.page,
                evidence_path=list(result.evidence_path),
                score=result.score,
                excerpt=self._truncate_excerpt(result.text),
            )
            for result in evidence.ranked_results
        ]

    def _truncate_excerpt(self, text: str) -> str:
        """Trim chunk text to the configured compact excerpt size."""

        tokenizer = self._tokenizer
        if tokenizer is not None:
            try:
                encoded = tokenizer(text, add_special_tokens=False, return_tensors=None)
            except TypeError:
                encoded = None
            if encoded is not None:
                input_ids = encoded.get("input_ids") if isinstance(encoded, dict) else None
                if input_ids is not None:
                    token_ids = (
                        input_ids[0]
                        if input_ids and isinstance(input_ids[0], list)
                        else input_ids
                    )
                    try:
                        return str(
                            tokenizer.decode(
                                token_ids[:USER_STORY_EVIDENCE_EXCERPT_TOKENS],
                                skip_special_tokens=True,
                            )
                        )
                    except Exception:
                        pass
        words = re.findall(r"\S+", text)
        if len(words) <= USER_STORY_EVIDENCE_EXCERPT_TOKENS:
            return text.strip()
        return " ".join(words[:USER_STORY_EVIDENCE_EXCERPT_TOKENS]).strip() + "..."

    async def _structured(
        self,
        *,
        instructions: str,
        payload: dict[str, Any],
        schema: type[T],
        schema_name: str,
        max_new_tokens: int | None = None,
    ) -> T:
        last_error: Exception | None = None
        for _attempt in range(2):
            raw = await asyncio.to_thread(
                self._create_response,
                instructions,
                payload,
                schema,
                schema_name,
                max_new_tokens,
                last_error,
            )
            try:
                return schema.model_validate(extract_json_object(raw))
            except (ValueError, ValidationError) as exc:
                last_error = exc
        assert last_error is not None
        raise MultiAgenticRagError(
            f"HuggingFace structured output failed for {schema_name}: {last_error}"
        ) from last_error

    def _create_response(
        self,
        instructions: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        schema_name: str,
        max_new_tokens: int | None,
        previous_error: Exception | None,
    ) -> str:
        tokenizer, model = self._load_model()
        effective_max_new_tokens = max_new_tokens or self.settings.hf_reason_max_new_tokens
        fit = self._fit_prompt(
            tokenizer=tokenizer,
            model=model,
            instructions=instructions,
            payload=payload,
            schema=schema,
            schema_name=schema_name,
            previous_error=previous_error,
            max_new_tokens=effective_max_new_tokens,
        )
        try:
            return self._generate_text(
                tokenizer=tokenizer,
                model=model,
                prompt=fit.prompt,
                max_new_tokens=fit.max_new_tokens,
            )
        except MultiAgenticRagError:
            raise
        except Exception as exc:
            raise MultiAgenticRagError(
                f"HuggingFace request failed for {schema_name}: {exc}"
            ) from exc

    def _load_model(self) -> tuple[Any, Any]:
        if self._tokenizer is not None and self._model is not None:
            return self._tokenizer, self._model
        self.settings.ensure_project_cache_paths()
        validate_hf_reasoning_environment(self.settings)
        try:
            transformers = cast(Any, import_module("transformers"))
            torch = cast(Any, import_module("torch"))
        except ModuleNotFoundError as exc:
            raise ConfigError(HF_REASONING_INSTALL_HINT) from exc

        tokenizer_loader = transformers.AutoTokenizer
        model_loader = transformers.AutoModelForCausalLM
        model_kwargs = self._model_load_kwargs(torch)
        try:
            tokenizer = tokenizer_loader.from_pretrained(
                self.settings.hf_reason_model,
                **self._hub_kwargs(),
            )
            model = model_loader.from_pretrained(
                self.settings.hf_reason_model,
                **self._hub_kwargs(),
                **model_kwargs,
            )
            if not _uses_auto_device(self.settings):
                model = model.to(self.settings.hf_reason_device)
        except Exception as exc:
            raise ConfigError(
                "Hugging Face reasoning model load failed for "
                f"{self.settings.hf_reason_model}: {exc}. "
                "Set HF_REASON_MODEL to a cached/available model and HF_TOKEN when needed."
            ) from exc
        self._tokenizer = tokenizer
        self._model = model
        return tokenizer, model

    def _model_load_kwargs(self, torch: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            "torch_dtype": self._torch_dtype(torch),
        }
        if _uses_auto_device(self.settings):
            kwargs["device_map"] = "auto"
        return kwargs

    def _hub_kwargs(self) -> dict[str, Any]:
        self.settings.ensure_project_cache_paths()
        kwargs: dict[str, Any] = {}
        if self.settings.hf_token:
            kwargs["token"] = self.settings.hf_token
        if self.settings.hf_reason_cache_dir:
            kwargs["cache_dir"] = str(Path(self.settings.hf_reason_cache_dir))
        return kwargs

    def _torch_dtype(self, torch: Any) -> Any:
        configured = self.settings.hf_reason_dtype.strip().lower()
        if configured == "auto":
            return "auto"
        aliases = {
            "float16": "float16",
            "fp16": "float16",
            "bfloat16": "bfloat16",
            "bf16": "bfloat16",
            "float32": "float32",
            "fp32": "float32",
        }
        dtype_name = aliases.get(configured)
        if dtype_name is None or not hasattr(torch, dtype_name):
            raise ConfigError(
                "Unsupported HF_REASON_DTYPE. Use auto, float16, bfloat16, or float32."
            )
        return getattr(torch, dtype_name)

    def _build_prompt(
        self,
        *,
        instructions: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        schema_name: str,
        previous_error: Exception | None,
    ) -> str:
        system = (
            f"{instructions}\n\n"
            "You are a structured JSON API. Return exactly one JSON object and no markdown, "
            "commentary, code fences, or extra text."
        )
        user_payload: dict[str, Any] = {
            "schema_name": schema_name,
            "json_schema": schema.model_json_schema(),
            "payload": payload,
        }
        if previous_error is not None:
            user_payload["previous_validation_error"] = _short_error(previous_error)
            user_payload["retry_instruction"] = (
                "Correct the prior output. Return JSON only and satisfy the schema."
            )
        user = json.dumps(user_payload, ensure_ascii=False, indent=2)
        tokenizer = self._tokenizer
        if tokenizer is None:
            return f"{system}\n\n{user}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            rendered = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=self.settings.hf_reason_enable_thinking,
            )
        except TypeError:
            rendered = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except AttributeError:
            return f"{system}\n\n{user}\n\n{{"
        return f"{rendered}\n{{"

    def _generate_text(
        self,
        *,
        tokenizer: Any,
        model: Any,
        prompt: str,
        max_new_tokens: int,
    ) -> str:
        encoded = tokenizer([prompt], return_tensors="pt")
        if hasattr(encoded, "to") and hasattr(model, "device"):
            encoded = encoded.to(model.device)
        input_ids = encoded["input_ids"]
        generation_kwargs = self._generation_kwargs(tokenizer, max_new_tokens=max_new_tokens)
        generated_ids = model.generate(**encoded, **generation_kwargs)
        output_ids = generated_ids[0][len(input_ids[0]) :]
        decoded = tokenizer.decode(output_ids, skip_special_tokens=True)
        return _restore_json_prefill(str(decoded))

    def _generation_kwargs(self, tokenizer: Any, *, max_new_tokens: int) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "max_new_tokens": max_new_tokens,
        }
        if self.settings.hf_reason_timeout_seconds > 0:
            kwargs["max_time"] = self.settings.hf_reason_timeout_seconds
        eos_token_id = getattr(tokenizer, "eos_token_id", None)
        if eos_token_id is not None:
            kwargs["eos_token_id"] = eos_token_id
            kwargs["pad_token_id"] = getattr(tokenizer, "pad_token_id", None) or eos_token_id
        if self.settings.hf_reason_temperature > 0:
            kwargs.update(
                {
                    "do_sample": True,
                    "temperature": self.settings.hf_reason_temperature,
                    "top_p": self.settings.hf_reason_top_p,
                    "top_k": self.settings.hf_reason_top_k,
                }
            )
        else:
            kwargs["do_sample"] = False
        return kwargs

    def _fit_prompt(
        self,
        *,
        tokenizer: Any,
        model: Any,
        instructions: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        schema_name: str,
        previous_error: Exception | None,
        max_new_tokens: int,
    ) -> PromptFitResult:
        """Fit a prompt within the available budget before generation."""

        model_window = self._model_window(tokenizer, model)
        budget = self._prompt_budget(model_window=model_window, max_new_tokens=max_new_tokens)
        if schema_name not in USER_STORY_SCHEMA_NAMES:
            prompt = self._build_prompt(
                instructions=instructions,
                payload=payload,
                schema=schema,
                schema_name=schema_name,
                previous_error=previous_error,
            )
            prompt_tokens = self._count_prompt_tokens(tokenizer, prompt)
            if prompt_tokens > budget:
                raise MultiAgenticRagError(
                    self._format_prompt_budget_error(
                        schema_name=schema_name,
                        prompt_tokens=prompt_tokens,
                        model_window=model_window,
                        max_new_tokens=max_new_tokens,
                        pruned_chunk_ids=(),
                        budget=budget,
                    )
                )
            return PromptFitResult(
                payload=payload,
                prompt=prompt,
                prompt_tokens=prompt_tokens,
                model_window=model_window,
                max_new_tokens=max_new_tokens,
            )

        return self._fit_user_story_prompt(
            tokenizer=tokenizer,
            model_window=model_window,
            budget=budget,
            instructions=instructions,
            payload=payload,
            schema=schema,
            schema_name=schema_name,
            previous_error=previous_error,
            max_new_tokens=max_new_tokens,
        )

    def _fit_user_story_prompt(
        self,
        *,
        tokenizer: Any,
        model_window: int,
        budget: int,
        instructions: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        schema_name: str,
        previous_error: Exception | None,
        max_new_tokens: int,
    ) -> PromptFitResult:
        """Compacts user-story evidence rows until the prompt fits or fails."""

        evidence = payload.get("evidence")
        if not isinstance(evidence, list):
            prompt = self._build_prompt(
                instructions=instructions,
                payload=payload,
                schema=schema,
                schema_name=schema_name,
                previous_error=previous_error,
            )
            prompt_tokens = self._count_prompt_tokens(tokenizer, prompt)
            if prompt_tokens > budget:
                raise MultiAgenticRagError(
                    self._format_prompt_budget_error(
                        schema_name=schema_name,
                        prompt_tokens=prompt_tokens,
                        model_window=model_window,
                        max_new_tokens=max_new_tokens,
                        pruned_chunk_ids=(),
                        budget=budget,
                    )
                )
            return PromptFitResult(
                payload=payload,
                prompt=prompt,
                prompt_tokens=prompt_tokens,
                model_window=model_window,
                max_new_tokens=max_new_tokens,
            )

        evidence_items = [item for item in evidence if isinstance(item, dict)]
        removed_chunk_ids: list[str] = []
        for remaining_count in range(len(evidence_items), -1, -1):
            candidate_items = evidence_items[:remaining_count]
            candidate_payload = dict(payload)
            candidate_payload["evidence"] = candidate_items
            prompt = self._build_prompt(
                instructions=instructions,
                payload=candidate_payload,
                schema=schema,
                schema_name=schema_name,
                previous_error=previous_error,
            )
            prompt_tokens = self._count_prompt_tokens(tokenizer, prompt)
            if prompt_tokens <= budget:
                return PromptFitResult(
                    payload=candidate_payload,
                    prompt=prompt,
                    prompt_tokens=prompt_tokens,
                    model_window=model_window,
                    max_new_tokens=max_new_tokens,
                    pruned_chunk_ids=tuple(removed_chunk_ids),
                )
            if remaining_count > 0:
                removed_chunk_ids.append(
                    str(evidence_items[remaining_count - 1].get("chunk_id", ""))
                )

        prompt = self._build_prompt(
            instructions=instructions,
            payload={**payload, "evidence": []},
            schema=schema,
            schema_name=schema_name,
            previous_error=previous_error,
        )
        prompt_tokens = self._count_prompt_tokens(tokenizer, prompt)
        raise MultiAgenticRagError(
            self._format_prompt_budget_error(
                schema_name=schema_name,
                prompt_tokens=prompt_tokens,
                model_window=model_window,
                max_new_tokens=max_new_tokens,
                pruned_chunk_ids=tuple(removed_chunk_ids),
                budget=budget,
            )
        )

    def _prompt_budget(self, *, model_window: int, max_new_tokens: int) -> int:
        return max(0, model_window - max_new_tokens - PROMPT_RESERVED_TOKENS)

    def _model_window(self, tokenizer: Any, model: Any) -> int:
        candidates: list[int] = []
        for value in (
            getattr(getattr(model, "config", None), "max_position_embeddings", None),
            getattr(getattr(model, "generation_config", None), "max_length", None),
            getattr(tokenizer, "model_max_length", None),
        ):
            if isinstance(value, int) and 0 < value < 1_000_000_000:
                candidates.append(value)
        return min(candidates) if candidates else DEFAULT_MODEL_WINDOW

    def _count_prompt_tokens(self, tokenizer: Any, prompt: str) -> int:
        encoded = tokenizer([prompt], return_tensors="pt")
        input_ids = encoded["input_ids"]
        return len(input_ids[0])

    def _format_prompt_budget_error(
        self,
        *,
        schema_name: str,
        prompt_tokens: int,
        model_window: int,
        max_new_tokens: int,
        pruned_chunk_ids: tuple[str, ...],
        budget: int,
    ) -> str:
        return (
            f"HuggingFace structured output prompt exceeded budget for {schema_name}: "
            f"prompt_tokens={prompt_tokens}, model_window={model_window}, "
            f"max_new_tokens={max_new_tokens}, input_budget={budget}, "
            f"pruned_chunk_ids={list(pruned_chunk_ids)}"
        )


def _restore_json_prefill(decoded: str) -> str:
    cleaned = decoded.lstrip()
    if cleaned.startswith("{"):
        return decoded
    return "{" + decoded


def _extractive_grounded_answer(question: str, evidence: EvidenceBundle) -> GroundedAnswer:
    threshold_answer = _threshold_grounded_answer(question, evidence)
    if threshold_answer is not None:
        return threshold_answer

    snippets = _select_evidence_snippets(question, evidence)
    citations = [
        result.chunk_id
        for result in evidence.ranked_results
        if result.chunk_id
    ]
    citations = list(dict.fromkeys(citations))
    if not snippets:
        return GroundedAnswer(
            answer="I could not extract a concise answer from the retrieved evidence.",
            refused=True,
            citations=citations[:5],
            validation_status="failed",
        )
    answer = "From the retrieved document evidence:\n" + "\n".join(
        f"- {snippet}" for snippet in snippets
    )
    source = _source_line(evidence.ranked_results[0]) if evidence.ranked_results else ""
    if source:
        answer = f"{answer}\n\nSource: {source}"
    return GroundedAnswer(
        answer=answer,
        refused=False,
        citations=citations[:5],
        validation_status="passed",
    )


def _threshold_grounded_answer(
    question: str,
    evidence: EvidenceBundle,
) -> GroundedAnswer | None:
    if not _is_threshold_question(question):
        return None
    rows = _extract_threshold_rows(evidence)
    if not rows:
        return None
    target = _select_threshold_row(question, rows)
    if target is None:
        if len(rows) != 1:
            sensors = ", ".join(row.sensor_label for row in rows)
            return GroundedAnswer(
                answer=(
                    "The document contains threshold rows for multiple sensors. "
                    f"Please specify one sensor: {sensors}."
                ),
                refused=True,
                citations=[row.chunk_id for row in rows[:5]],
                validation_status="failed",
            )
        target = rows[0]
    requested_fields = _requested_threshold_fields(question)
    lines = [
        f"I interpreted the question as asking for the {target.sensor_label} threshold bands.",
        "",
        f"As per document version {target.version}, the {target.sensor_label} thresholds are:",
    ]
    for key, label in THRESHOLD_COLUMNS:
        if key not in requested_fields or key not in target.values:
            continue
        value = target.values[key]
        if key == "normal_range":
            label = "Normal range (baseline/average operating range)"
        lines.append(f"- {label}: {value}")
    lines.extend(["", f"Source: {_threshold_source_line(target)}"])
    return GroundedAnswer(
        answer="\n".join(lines),
        refused=False,
        citations=[target.chunk_id],
        validation_status="passed",
    )


def _is_threshold_question(question: str) -> bool:
    terms = _query_terms(question)
    return bool(terms & {"threshold", "thresholds", "range", "critical", "minimum", "maximum"})


def _extract_threshold_rows(evidence: EvidenceBundle) -> list[ThresholdAnswerRow]:
    rows: list[ThresholdAnswerRow] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...], str]] = set()
    for result in evidence.ranked_results:
        text = re.sub(r"\s+", " ", result.text).strip()
        matches = list(SENSOR_ROW_PATTERN.finditer(text))
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            values = [
                _normalize_threshold_value(value.group(0))
                for value in THRESHOLD_VALUE_PATTERN.finditer(text[start:end])
            ][: len(THRESHOLD_COLUMNS)]
            if len(values) < len(THRESHOLD_COLUMNS):
                continue
            value_map = {
                key: value
                for (key, _label), value in zip(THRESHOLD_COLUMNS, values, strict=True)
            }
            sensor_label = match.group("sensor").strip()
            identity = (sensor_label.lower(), tuple(value_map.items()), result.chunk_id)
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(
                ThresholdAnswerRow(
                    sensor_label=sensor_label,
                    values=value_map,
                    chunk_id=result.chunk_id,
                    source_name=result.source_name,
                    page=result.page,
                    version=result.version,
                )
            )
    return rows


def _select_threshold_row(
    question: str,
    rows: list[ThresholdAnswerRow],
) -> ThresholdAnswerRow | None:
    terms = _query_terms(question)
    best: tuple[int, ThresholdAnswerRow] | None = None
    for row in rows:
        sensor_terms = _query_terms(row.sensor_label)
        sensor_terms.discard("sensor")
        score = len(terms & sensor_terms)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, row)
    return best[1] if best else None


def _requested_threshold_fields(question: str) -> set[str]:
    terms = _query_terms(question)
    fields = {
        key
        for key, field_terms in THRESHOLD_FIELD_TERMS.items()
        if terms & field_terms
    }
    threshold_only = terms & {"threshold", "thresholds"}
    return fields or (set(THRESHOLD_FIELD_TERMS) if threshold_only else set(THRESHOLD_FIELD_TERMS))


def _normalize_threshold_value(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    normalized = normalized.replace("° C", "°C").replace("° F", "°F")
    return normalized


def _threshold_source_line(row: ThresholdAnswerRow) -> str:
    return f"{row.source_name}, page {row.page}, chunk {row.chunk_id}"


def _source_line(result: Any) -> str:
    return f"{result.source_name}, page {result.page}, chunk {result.chunk_id}"


def _select_evidence_snippets(
    question: str,
    evidence: EvidenceBundle,
    *,
    limit: int = 2,
) -> list[str]:
    query_terms = _query_terms(question)
    scored: list[tuple[int, int, str]] = []
    for result in evidence.ranked_results:
        for sentence_index, sentence in enumerate(_sentences(result.text)):
            normalized = sentence.lower()
            overlap = sum(1 for term in query_terms if term in normalized)
            if overlap <= 0 and scored:
                continue
            scored.append((overlap, -sentence_index, _truncate(sentence)))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    snippets: list[str] = []
    seen: set[str] = set()
    for _, _, snippet in scored:
        key = snippet.lower()
        if key in seen:
            continue
        seen.add(key)
        snippets.append(snippet)
        if len(snippets) == limit:
            break
    return snippets


def _sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    sentences = [
        sentence.strip(" -;\t")
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", cleaned)
        if sentence.strip(" -;\t")
    ]
    return sentences or [cleaned]


def _query_terms(question: str) -> set[str]:
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "for",
        "in",
        "is",
        "of",
        "the",
        "to",
        "what",
        "which",
        "with",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", question.lower())
        if len(token) > 2 and token not in stop_words
    }


def _truncate(text: str, *, limit: int = 420) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _short_error(error: Exception, *, limit: int = 1200) -> str:
    text = str(error)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def inspect_hf_reasoning_environment(
    settings: Settings | None = None,
) -> HFReasoningEnvironmentReport:
    """Inspect HF reasoning dependencies and device state without loading a model."""

    loaded_settings = settings or get_settings()
    dependency_names = list(HF_BASE_DEPENDENCIES)
    accelerate_required = _uses_auto_device(loaded_settings)
    if accelerate_required:
        dependency_names.append(HF_AUTO_DEVICE_DEPENDENCY)

    dependencies: list[HFDependencyStatus] = []
    imported_modules: dict[str, Any] = {}
    for name in dependency_names:
        dependency, module = _inspect_dependency(name)
        dependencies.append(dependency)
        if module is not None:
            imported_modules[name] = module

    (
        cuda_available,
        cuda_device_count,
        cuda_version,
        torch_version,
        torch_cuda_built,
        cuda_device_name,
    ) = _inspect_torch_cuda(imported_modules.get("torch"))
    nvidia_smi_available = _nvidia_smi_available()
    return HFReasoningEnvironmentReport(
        model=loaded_settings.hf_reason_model,
        device=loaded_settings.hf_reason_device,
        dtype=loaded_settings.hf_reason_dtype,
        max_new_tokens=loaded_settings.hf_reason_max_new_tokens,
        validation_max_new_tokens=loaded_settings.hf_reason_validation_max_new_tokens,
        timeout_seconds=loaded_settings.hf_reason_timeout_seconds,
        answer_mode=loaded_settings.hf_reason_answer_mode,
        cache_dir=Path(loaded_settings.hf_reason_cache_dir),
        token_present=bool(loaded_settings.hf_token),
        fact_review_policy="opt-in with --review-facts",
        accelerate_required=accelerate_required,
        dependencies=tuple(dependencies),
        cuda_available=cuda_available,
        cuda_device_count=cuda_device_count,
        cuda_version=cuda_version,
        torch_version=torch_version,
        torch_cuda_built=torch_cuda_built,
        cuda_device_name=cuda_device_name,
        nvidia_smi_available=nvidia_smi_available,
        gpu_install_command=(
            HF_REASONING_GPU_INSTALL_COMMAND
            if nvidia_smi_available
            and torch_version is not None
            and cuda_available is False
            and cuda_version is None
            and torch_cuda_built is False
            else None
        ),
    )


def validate_hf_reasoning_environment(
    settings: Settings | None = None,
) -> HFReasoningEnvironmentReport:
    """Raise a clear configuration error if HF reasoning cannot start."""

    report = inspect_hf_reasoning_environment(settings)
    if not report.dependencies_ready:
        raise ConfigError(format_hf_reasoning_preflight_error(report))
    return report


def format_hf_reasoning_preflight_error(report: HFReasoningEnvironmentReport) -> str:
    """Build the actionable HF dependency error used by CLI and model loading."""

    missing = ", ".join(report.missing_required_dependencies)
    message = (
        "Hugging Face reasoning dependencies are incomplete. "
        f"Missing required package(s): {missing}. "
        f"{HF_REASONING_INSTALL_HINT}"
    )
    if HF_AUTO_DEVICE_DEPENDENCY in report.missing_required_dependencies:
        message += (
            ' HF_REASON_DEVICE=auto uses Transformers device_map="auto", which requires '
            "accelerate. On CPU-only machines, set HF_REASON_DEVICE=cpu to avoid device_map; "
            "large models such as Qwen/Qwen3-8B will still be slow on CPU."
        )
    return message


def _inspect_dependency(name: str) -> tuple[HFDependencyStatus, Any | None]:
    try:
        module = import_module(name)
    except ModuleNotFoundError as exc:
        return (
            HFDependencyStatus(
                name=name,
                installed=False,
                error=str(exc),
            ),
            None,
        )
    except Exception as exc:
        return (
            HFDependencyStatus(
                name=name,
                installed=False,
                error=f"{type(exc).__name__}: {exc}",
            ),
            None,
        )
    version = getattr(module, "__version__", None)
    return (
        HFDependencyStatus(
            name=name,
            installed=True,
            version=str(version) if version is not None else None,
        ),
        module,
    )


def _inspect_torch_cuda(
    torch: Any | None,
) -> tuple[bool | None, int | None, str | None, str | None, bool | None, str | None]:
    if torch is None:
        return None, None, None, None, None, None
    raw_torch_version = getattr(torch, "__version__", None)
    torch_version = str(raw_torch_version) if raw_torch_version is not None else None
    torch_version_module = getattr(torch, "version", None)
    raw_cuda_version = getattr(torch_version_module, "cuda", None)
    cuda_version = str(raw_cuda_version) if raw_cuda_version is not None else None
    cuda_built = _inspect_torch_cuda_build(torch)
    cuda = getattr(torch, "cuda", None)
    if cuda is None or not hasattr(cuda, "is_available"):
        return None, None, cuda_version, torch_version, cuda_built, None
    try:
        cuda_available = bool(cuda.is_available())
    except Exception:
        return None, None, cuda_version, torch_version, cuda_built, None
    device_count: int | None = None
    if hasattr(cuda, "device_count"):
        try:
            device_count = int(cuda.device_count())
        except Exception:
            device_count = None
    device_name: str | None = None
    if cuda_available and hasattr(cuda, "get_device_name"):
        try:
            device_name = str(cuda.get_device_name(0))
        except Exception:
            device_name = None
    return cuda_available, device_count, cuda_version, torch_version, cuda_built, device_name


def _inspect_torch_cuda_build(torch: Any) -> bool | None:
    backends = getattr(torch, "backends", None)
    cuda_backend = getattr(backends, "cuda", None)
    is_built = getattr(cuda_backend, "is_built", None)
    if callable(is_built):
        try:
            return bool(is_built())
        except Exception:
            return None
    return None


def _nvidia_smi_available() -> bool:
    return shutil.which("nvidia-smi") is not None


def _uses_auto_device(settings: Settings) -> bool:
    return settings.hf_reason_device.strip().lower() == "auto"
