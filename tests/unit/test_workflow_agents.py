from __future__ import annotations

import asyncio
import json
import os

import pytest
from typer.testing import CliRunner

import multi_agentic_rag.cli as cli
from multi_agentic_rag.agents.high_level import AgentRetrieveAnswer, AgentUserStoryBuilder
from multi_agentic_rag.agents.sub_agents import FactEnrichmentAgent
from multi_agentic_rag.agents.tools import build_default_tool_registry
from multi_agentic_rag.agents.workflow import (
    FlowValidatorAgent,
    IntentRouterAgent,
    LangGraphWorkflowRunner,
    WorkflowPlannerAgent,
    default_workflow_plan,
)
from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import (
    AgentRunResult,
    AgentRunStatus,
    ChunkRecord,
    DocumentStatus,
    EvidenceBundle,
    FactEnrichmentBatch,
    FactEnrichmentSuggestion,
    FactRecord,
    FactSplitSuggestion,
    GeneratedUserStory,
    GeneratedUserStoryBatch,
    GroundedAnswer,
    IngestResult,
    QualityValidationReport,
    RankedRetrievalResult,
    RetrievalResult,
    TaskIntent,
    TaskIntentType,
    WorkflowPlan,
    WorkflowStatus,
)
from multi_agentic_rag.exceptions import ConfigError, MultiAgenticRagError
from multi_agentic_rag.llm import (
    HuggingFaceReasoningClient,
    OpenAIReasoningClient,
    build_reasoning_client,
    inspect_hf_reasoning_environment,
    validate_hf_reasoning_environment,
)
from multi_agentic_rag.llm.openai_reasoning import strict_openai_schema
from multi_agentic_rag.llm.prompts import USER_STORY_PROMPT
from multi_agentic_rag.llm.structured import LLMGeneratedUserStoryBatch

PROJECT_CACHE_ENV_VARS = (
    "PROJECT_ROOT",
    "GLOBAL_CACHE_DIR",
    "MODEL_CACHE_DIR",
    "DATABASE_CACHE_DIR",
    "VECTORSTORE_CACHE_DIR",
    "GRAPH_CACHE_DIR",
    "HF_HOME",
    "TRANSFORMERS_CACHE",
    "SENTENCE_TRANSFORMERS_HOME",
    "TORCH_HOME",
    "HF_REASON_CACHE_DIR",
    "CHROMA_PATH",
    "MULTI_AGENTIC_RAG_HOME",
    "DOCUMENT_STORE_PATH",
    "OBJECT_STORE_PATH",
    "MANIFEST_STORE_PATH",
)


def test_tool_registry_exposes_shared_operations() -> None:
    registry = build_default_tool_registry()

    assert "document.parse" in registry.names()
    assert "retrieval.hybrid" in registry.names()
    assert "artifact.write" in registry.names()


def test_openai_reasoning_client_parses_structured_output() -> None:
    fake_openai = FakeOpenAIClient(
        {
            "intent_type": "answer_query",
            "system": "PROJECT_1",
            "kb": "default",
            "version": "v1",
            "documents": [],
            "output_request": None,
            "missing_slots": [],
            "confidence": 1.0,
        }
    )
    intent = asyncio.run(
        OpenAIReasoningClient(
            Settings(postgres_dsn="postgresql+asyncpg://x"),
            client=fake_openai,
        ).route_intent("ask", defaults={"system": "PROJECT_1"})
    )

    assert intent.intent_type == TaskIntentType.ANSWER_QUERY
    assert fake_openai.responses.calls[0]["model"] == "gpt-5.5"
    assert fake_openai.responses.calls[0]["text"]["format"]["type"] == "json_schema"
    assert fake_openai.responses.calls[0]["text"]["format"]["strict"] is True
    _assert_strict_schema(fake_openai.responses.calls[0]["text"]["format"]["schema"])


def test_openai_grounded_answer_schema_is_strict_compatible() -> None:
    fake_openai = FakeOpenAIClient(
        {
            "answer": "The threshold is 80 C.",
            "refused": False,
            "citations": ["chunk-1"],
            "validation_status": "passed",
        }
    )
    answer = asyncio.run(
        OpenAIReasoningClient(
            Settings(postgres_dsn="postgresql+asyncpg://x"),
            client=fake_openai,
        ).synthesize_answer("What is the threshold?", EvidenceBundle(query="q"))
    )

    assert answer.citations == ["chunk-1"]
    _assert_strict_schema(fake_openai.responses.calls[0]["text"]["format"]["schema"])


def test_openai_user_story_schema_uses_closed_traceability_dto() -> None:
    fake_openai = FakeOpenAIClient(
        {
            "stories": [
                {
                    "id": "US-001",
                    "title": "Monitor threshold",
                    "type": "functional",
                    "domain": "industrial",
                    "priority": "high",
                    "status": "draft",
                    "persona": "operator",
                    "user_story": "As an operator, I want threshold monitoring.",
                    "business_value": "Prevent unsafe operation.",
                    "description": "Monitor the documented threshold.",
                    "acceptance_criteria": ["Given evidence, then alert."],
                    "non_functional_requirements": [],
                    "dependencies": [],
                    "definition_of_ready": [],
                    "definition_of_done": [],
                    "traceability": {
                        "chunk_ids": ["chunk-1"],
                        "requirement_ids": ["REQ-1"],
                        "fact_ids": ["fact-1"],
                        "evidence_paths": [["Chunk:chunk-1"]],
                    },
                }
            ],
            "reasoning_summary": "Generated from evidence.",
        }
    )
    batch = asyncio.run(
        OpenAIReasoningClient(
            Settings(postgres_dsn="postgresql+asyncpg://x"),
            client=fake_openai,
        ).write_user_stories(EvidenceBundle(query="q", source_chunk_ids=["chunk-1"]))
    )

    assert batch.stories[0].traceability["chunk_ids"] == ["chunk-1"]
    _assert_strict_schema(fake_openai.responses.calls[0]["text"]["format"]["schema"])


def test_openai_reasoning_client_rejects_invalid_structured_output() -> None:
    with pytest.raises(MultiAgenticRagError, match="structured output failed validation"):
        asyncio.run(
            OpenAIReasoningClient(
                Settings(postgres_dsn="postgresql+asyncpg://x"),
                client=FakeOpenAIClient({"unexpected": "shape"}),
            ).route_intent("ask")
        )


def test_openai_reasoning_client_wraps_request_errors_with_schema_name() -> None:
    with pytest.raises(MultiAgenticRagError, match="task_intent: invalid_json_schema"):
        asyncio.run(
            OpenAIReasoningClient(
                Settings(postgres_dsn="postgresql+asyncpg://x"),
                client=FakeOpenAIClient(error=RuntimeError("invalid_json_schema")),
            ).route_intent("ask")
        )


def test_strict_schema_adapter_closes_nested_objects() -> None:
    schema = strict_openai_schema(GeneratedUserStoryBatch)

    _assert_strict_schema(schema)


def test_hf_reasoning_client_parses_structured_outputs() -> None:
    tokenizer = FakeHFTokenizer(
        [
            {
                "intent_type": "answer_query",
                "system": "PROJECT_1",
                "kb": "default",
                "version": "v1",
                "documents": [],
                "output_request": None,
                "missing_slots": [],
                "confidence": 1.0,
            },
            {
                "answer": "The threshold is 80 C.",
                "refused": False,
                "citations": ["chunk-1"],
                "validation_status": "passed",
            },
            {
                "stories": [
                    {
                        "id": "US-001",
                        "title": "Monitor threshold",
                        "type": "functional",
                        "domain": "industrial",
                        "priority": "high",
                        "status": "draft",
                        "persona": "operator",
                        "user_story": "As an operator, I want threshold monitoring.",
                        "business_value": "Prevent unsafe operation.",
                        "description": "Monitor the documented threshold.",
                        "acceptance_criteria": ["Given evidence, then alert."],
                        "non_functional_requirements": [],
                        "dependencies": [],
                        "definition_of_ready": [],
                        "definition_of_done": [],
                        "traceability": {
                            "chunk_ids": ["chunk-1"],
                            "requirement_ids": ["REQ-1"],
                            "fact_ids": ["fact-1"],
                            "evidence_paths": [["Chunk:chunk-1"]],
                        },
                    }
                ],
                "reasoning_summary": "Generated from evidence.",
            },
            {
                "status": "passed",
                "messages": [],
                "checks": {
                    "evidence_traceable": True,
                    "citations_supported": True,
                    "schema_complete": True,
                    "unsupported_claims_absent": True,
                },
            },
            {
                "suggestions": [
                    {
                        "fact_id": "fact-1",
                        "fact_key": "threshold:temperature",
                        "review_status": "validated",
                        "canonical_name": "temperature",
                        "relationship_hint": "THRESHOLD_FOR",
                        "split_candidates": [],
                        "uncertain_relationships": [],
                        "confidence": 0.9,
                        "reasoning_summary": "Traceable.",
                    }
                ],
                "reasoning_summary": "Reviewed.",
            },
        ]
    )
    client = HuggingFaceReasoningClient(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            hf_reason_answer_mode="generative",
            hf_reason_enable_thinking=False,
        ),
        tokenizer=tokenizer,
        model=FakeHFModel(),
    )
    evidence = EvidenceBundle(query="q", source_chunk_ids=["chunk-1"])
    story = GeneratedUserStory(
        id="US-001",
        title="Monitor threshold",
        type="functional",
        domain="industrial",
        priority="high",
        status="draft",
        persona="operator",
        user_story="As an operator, I want threshold monitoring.",
        business_value="Prevent unsafe operation.",
        description="Monitor the documented threshold.",
        traceability={"chunk_ids": ["chunk-1"]},
    )

    intent = asyncio.run(client.route_intent("ask", defaults={"system": "PROJECT_1"}))
    answer = asyncio.run(client.synthesize_answer("What is the threshold?", evidence))
    batch = asyncio.run(client.write_user_stories(evidence))
    validation = asyncio.run(client.validate_user_story(story, evidence))
    review = asyncio.run(
        client.review_facts(
            chunk_text="REQ-1 temperature threshold maximum is 80 C.",
            facts=[{"fact_id": "fact-1", "fact_key": "threshold:temperature"}],
        )
    )

    assert intent.intent_type == TaskIntentType.ANSWER_QUERY
    assert answer.citations == ["chunk-1"]
    assert batch.stories[0].traceability["chunk_ids"] == ["chunk-1"]
    assert validation.status == "passed"
    assert review.suggestions[0].canonical_name == "temperature"
    assert tokenizer.chat_template_calls[0]["enable_thinking"] is False


def test_hf_reasoning_user_story_prompt_keeps_all_validated_chunks_within_window() -> None:
    tokenizer = CountingHFTokenizer([])
    model = FakeHFModel(model_window=40960)
    client = HuggingFaceReasoningClient(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            hf_reason_answer_mode="generative",
        ),
        tokenizer=tokenizer,
        model=model,
    )
    evidence = _user_story_evidence_bundle(chunk_count=13)
    payload = client._build_user_story_prompt_payload(evidence)

    fit = client._fit_prompt(
        tokenizer=tokenizer,
        model=model,
        instructions=USER_STORY_PROMPT,
        payload=payload,
        schema=LLMGeneratedUserStoryBatch,
        schema_name="generated_user_story_batch",
        previous_error=None,
        max_new_tokens=client.settings.hf_reason_max_new_tokens,
    )

    assert [item["chunk_id"] for item in fit.payload["evidence"]] == evidence.source_chunk_ids
    assert fit.prompt_tokens <= fit.model_window - client.settings.hf_reason_max_new_tokens - 2048
    assert fit.pruned_chunk_ids == ()
    compact_keys = {
        "chunk_id",
        "rank",
        "source_name",
        "page",
        "evidence_path",
        "score",
        "excerpt",
    }
    assert all(
        set(item) == compact_keys
        for item in fit.payload["evidence"]
    )


def test_hf_reasoning_user_story_generation_uses_compact_payload() -> None:
    tokenizer = FakeHFTokenizer(
        [
            {
                "stories": [
                    {
                        "id": "US-001",
                        "title": "Monitor threshold",
                        "type": "functional",
                        "domain": "industrial",
                        "priority": "high",
                        "status": "draft",
                        "persona": "operator",
                        "user_story": "As an operator, I want threshold monitoring.",
                        "business_value": "Prevent unsafe operation.",
                        "description": "Monitor the documented threshold.",
                        "acceptance_criteria": ["Given evidence, then alert."],
                        "non_functional_requirements": [],
                        "dependencies": [],
                        "definition_of_ready": [],
                        "definition_of_done": [],
                        "traceability": {
                            "chunk_ids": ["chunk-1", "chunk-2", "chunk-3"],
                            "requirement_ids": [],
                            "fact_ids": [],
                            "evidence_paths": [["Chunk:chunk-1"]],
                        },
                    }
                ],
                "reasoning_summary": "Generated from evidence.",
            }
        ]
    )
    client = HuggingFaceReasoningClient(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            hf_reason_answer_mode="generative",
            hf_reason_enable_thinking=False,
        ),
        tokenizer=tokenizer,
        model=FakeHFModel(),
    )
    evidence = _user_story_evidence_bundle(chunk_count=3)

    batch = asyncio.run(client.write_user_stories(evidence))
    payload = json.loads(tokenizer.user_payloads[0])

    assert batch.stories[0].id == "US-001"
    assert payload["schema_name"] == "generated_user_story_batch"
    assert payload["payload"]["story"] is None
    assert [
        item["chunk_id"] for item in payload["payload"]["evidence"]
    ] == evidence.source_chunk_ids
    compact_keys = {
        "chunk_id",
        "rank",
        "source_name",
        "page",
        "evidence_path",
        "score",
        "excerpt",
    }
    assert all(
        set(item) == compact_keys
        for item in payload["payload"]["evidence"]
    )
    assert "ranked_results" not in payload["payload"]
    assert "source_chunk_ids" not in payload["payload"]
    assert "graph_paths" not in payload["payload"]


def test_hf_reasoning_user_story_validation_uses_compact_payload() -> None:
    tokenizer = FakeHFTokenizer(
        [
            {
                "status": "passed",
                "messages": [],
                "checks": {
                    "evidence_traceable": True,
                    "citations_supported": True,
                    "schema_complete": True,
                    "unsupported_claims_absent": True,
                },
            }
        ]
    )
    client = HuggingFaceReasoningClient(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            hf_reason_answer_mode="generative",
            hf_reason_enable_thinking=False,
        ),
        tokenizer=tokenizer,
        model=FakeHFModel(),
    )
    evidence = _user_story_evidence_bundle(chunk_count=3)
    story = GeneratedUserStory(
        id="US-001",
        title="Monitor threshold",
        type="functional",
        domain="industrial",
        priority="high",
        status="draft",
        persona="operator",
        user_story="As an operator, I want threshold monitoring.",
        business_value="Prevent unsafe operation.",
        description="Monitor the documented threshold.",
        acceptance_criteria=["Given evidence, then alert."],
        non_functional_requirements=[],
        dependencies=[],
        definition_of_ready=[],
        definition_of_done=[],
        traceability={"chunk_ids": ["chunk-1", "chunk-2", "chunk-3"]},
    )

    report = asyncio.run(client.validate_user_story(story, evidence))
    payload = json.loads(tokenizer.user_payloads[0])

    assert report.status == "passed"
    assert payload["schema_name"] == "quality_validation_report"
    assert payload["payload"]["story"]["id"] == "US-001"
    assert [
        item["chunk_id"] for item in payload["payload"]["evidence"]
    ] == evidence.source_chunk_ids
    compact_keys = {
        "chunk_id",
        "rank",
        "source_name",
        "page",
        "evidence_path",
        "score",
        "excerpt",
    }
    assert all(
        set(item) == compact_keys
        for item in payload["payload"]["evidence"]
    )
    assert "ranked_results" not in payload["payload"]
    assert "source_chunk_ids" not in payload["payload"]
    assert "graph_paths" not in payload["payload"]


def test_hf_reasoning_user_story_validation_overflow_raises_budget_error() -> None:
    tokenizer = CountingHFTokenizer([])
    model = FakeHFModel(model_window=120)
    client = HuggingFaceReasoningClient(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            hf_reason_answer_mode="generative",
            hf_reason_enable_thinking=False,
        ),
        tokenizer=tokenizer,
        model=model,
    )
    evidence = _user_story_evidence_bundle(chunk_count=2, words_per_chunk=1500)
    story = GeneratedUserStory(
        id="US-001",
        title="Monitor threshold",
        type="functional",
        domain="industrial",
        priority="high",
        status="draft",
        persona="operator",
        user_story="As an operator, I want threshold monitoring.",
        business_value="Prevent unsafe operation.",
        description="Monitor the documented threshold.",
        acceptance_criteria=["Given evidence, then alert."],
        non_functional_requirements=[],
        dependencies=[],
        definition_of_ready=[],
        definition_of_done=[],
        traceability={"chunk_ids": evidence.source_chunk_ids},
    )

    with pytest.raises(
        MultiAgenticRagError,
        match=r"(?s)(?=.*quality_validation_report)(?=.*prompt_tokens=)(?=.*model_window=)(?=.*pruned_chunk_ids=)(?=.*chunk-1)(?=.*chunk-2)",
    ):
        asyncio.run(client.validate_user_story(story, evidence))

    assert tokenizer.generate_calls == 0


def test_hf_reasoning_user_story_generation_overflow_raises_budget_error() -> None:
    tokenizer = CountingHFTokenizer([])
    model = FakeHFModel(model_window=120)
    client = HuggingFaceReasoningClient(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            hf_reason_answer_mode="generative",
            hf_reason_enable_thinking=False,
        ),
        tokenizer=tokenizer,
        model=model,
    )
    evidence = _user_story_evidence_bundle(chunk_count=2, words_per_chunk=1500)

    with pytest.raises(
        MultiAgenticRagError,
        match=r"(?s)(?=.*generated_user_story_batch)(?=.*prompt_tokens=)(?=.*model_window=)(?=.*pruned_chunk_ids=)(?=.*chunk-1)(?=.*chunk-2)",
    ):
        asyncio.run(client.write_user_stories(evidence))

    assert tokenizer.generate_calls == 0


def test_hf_reasoning_deterministic_answer_mode_does_not_load_qwen(monkeypatch) -> None:
    client = HuggingFaceReasoningClient(Settings(postgres_dsn="postgresql+asyncpg://x"))

    def fail_load_model() -> tuple[object, object]:
        raise AssertionError("deterministic answer mode should not load Qwen")

    monkeypatch.setattr(client, "_load_model", fail_load_model)

    answer = asyncio.run(
        client.synthesize_answer(
            "What is the temperature threshold?",
            EvidenceBundle(
                query="What is the temperature threshold?",
                ranked_results=[
                    _ranked_result("REQ-1 temperature threshold maximum is 80 C.")
                ],
                source_chunk_ids=["chunk-1"],
            ),
        )
    )

    assert answer.refused is False
    assert "80 C" in answer.answer
    assert answer.citations == ["chunk-1"]


def test_hf_reasoning_threshold_answer_formats_requested_sensor_only() -> None:
    client = HuggingFaceReasoningClient(Settings(postgres_dsn="postgresql+asyncpg://x"))
    table_text = (
        "6.9 Sensor and Actuator Data Sheet Type Normal Range Min Threshold "
        "Max Threshold Critical Level Temperature Sensor 10-50°C 5-10°C "
        "50-70°C >70°C Vibration Sensor 1-5 mm/s 0-1 mm/s 5-8 mm/s "
        ">8 mm/s Gas Sensor 10-12 psi 5-10 psi 12-13 psi >13 psi "
        "Condition Safety Level Expected Action Temperature exceeds threshold "
        "Medium Increase fan speed."
    )

    answer = asyncio.run(
        client.synthesize_answer(
            "What is the temperature threshold?",
            EvidenceBundle(
                query="What is the temperature threshold?",
                ranked_results=[
                    _ranked_result(
                        table_text,
                        source_name="SIIMCS_BRD_V1.pdf",
                        page=5,
                    )
                ],
                source_chunk_ids=["chunk-1"],
                version_scope="v1",
            ),
        )
    )

    assert "Temperature Sensor thresholds" in answer.answer
    assert "- Normal range (baseline/average operating range): 10-50°C" in answer.answer
    assert "- Minimum threshold: 5-10°C" in answer.answer
    assert "- Maximum threshold: 50-70°C" in answer.answer
    assert "- Critical level: >70°C" in answer.answer
    assert "Vibration" not in answer.answer
    assert "Increase fan speed" not in answer.answer
    assert "SIIMCS_BRD_V1.pdf, page 5" in answer.answer


def test_hf_reasoning_generative_answer_falls_back_to_extracts() -> None:
    tokenizer = FakeHFTokenizer(["not json", "still not json"])
    client = HuggingFaceReasoningClient(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            hf_reason_answer_mode="generative",
        ),
        tokenizer=tokenizer,
        model=FakeHFModel(),
    )

    answer = asyncio.run(
        client.synthesize_answer(
            "What is the temperature threshold?",
            EvidenceBundle(
                query="What is the temperature threshold?",
                ranked_results=[
                    _ranked_result("REQ-1 temperature threshold maximum is 80 C.")
                ],
                source_chunk_ids=["chunk-1"],
            ),
        )
    )

    assert tokenizer.generate_calls == 2
    assert answer.refused is False
    assert "80 C" in answer.answer
    assert answer.citations == ["chunk-1"]


def test_hf_reasoning_client_retries_invalid_json_once_then_raises() -> None:
    tokenizer = FakeHFTokenizer(
        [
            "not json",
            {"unexpected": "shape"},
        ]
    )
    client = HuggingFaceReasoningClient(
        Settings(postgres_dsn="postgresql+asyncpg://x"),
        tokenizer=tokenizer,
        model=FakeHFModel(),
    )

    with pytest.raises(
        MultiAgenticRagError,
        match="HuggingFace structured output failed for task_intent",
    ):
        asyncio.run(client.route_intent("ask"))

    assert len(tokenizer.decoded_outputs) == 0
    assert tokenizer.generate_calls == 2
    retry_payload = json.loads(tokenizer.user_payloads[1])
    assert "previous_validation_error" in retry_payload


def test_hf_reasoning_client_missing_dependencies_has_install_hint(monkeypatch) -> None:
    def fake_import_module(name: str):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("multi_agentic_rag.llm.hf_reasoning.import_module", fake_import_module)
    client = HuggingFaceReasoningClient(Settings(postgres_dsn="postgresql+asyncpg://x"))

    with pytest.raises(ConfigError, match="uv sync --dev --extra hf-reasoning"):
        asyncio.run(client.route_intent("ask"))


def test_hf_reasoning_preflight_requires_accelerate_for_auto(monkeypatch) -> None:
    monkeypatch.setattr(
        "multi_agentic_rag.llm.hf_reasoning.import_module",
        _fake_hf_importer(missing={"accelerate"}),
    )
    client = HuggingFaceReasoningClient(
        Settings(postgres_dsn="postgresql+asyncpg://x", hf_reason_device="auto")
    )

    with pytest.raises(ConfigError, match='device_map="auto"'):
        client._load_model()


def test_hf_reasoning_cpu_device_does_not_require_accelerate(monkeypatch) -> None:
    imported_names: list[str] = []

    def fake_import_module(name: str):
        imported_names.append(name)
        if name == "accelerate":
            raise AssertionError("accelerate should not be imported for cpu device")
        return _fake_hf_module(name)

    monkeypatch.setattr(
        "multi_agentic_rag.llm.hf_reasoning.import_module",
        fake_import_module,
    )
    settings = Settings(postgres_dsn="postgresql+asyncpg://x", hf_reason_device="cpu")
    client = HuggingFaceReasoningClient(settings)

    report = validate_hf_reasoning_environment(settings)
    model_kwargs = client._model_load_kwargs(FakeHFTorchModule())

    assert report.dependencies_ready is True
    assert report.accelerate_required is False
    assert "accelerate" not in imported_names
    assert "device_map" not in model_kwargs


def test_hf_reasoning_report_detects_cpu_only_torch_with_nvidia(monkeypatch) -> None:
    monkeypatch.setattr(
        "multi_agentic_rag.llm.hf_reasoning.import_module",
        _fake_hf_importer(),
    )
    monkeypatch.setattr(
        "multi_agentic_rag.llm.hf_reasoning.shutil.which",
        lambda name: "nvidia-smi" if name == "nvidia-smi" else None,
    )

    report = inspect_hf_reasoning_environment(
        Settings(postgres_dsn="postgresql+asyncpg://x")
    )

    assert report.torch_version == "2.6.0+cpu"
    assert report.torch_cuda_built is False
    assert report.cuda_version is None
    assert report.cuda_available is False
    assert report.nvidia_smi_available is True
    assert report.torch_cpu_only_with_nvidia_driver is True
    assert (
        report.gpu_install_command
        == "uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy"
    )


def test_hf_reasoning_report_detects_cuda_torch_details(monkeypatch) -> None:
    cuda_torch = FakeHFTorchModule(
        version="2.12.0+cu130",
        cuda_available=True,
        cuda_version="13.0",
        cuda_built=True,
        device_count=1,
        device_name="NVIDIA GeForce RTX 4070",
    )

    def fake_import_module(name: str):
        if name == "torch":
            return cuda_torch
        return FakeHFModule(name)

    monkeypatch.setattr("multi_agentic_rag.llm.hf_reasoning.import_module", fake_import_module)
    monkeypatch.setattr(
        "multi_agentic_rag.llm.hf_reasoning.shutil.which",
        lambda name: "nvidia-smi" if name == "nvidia-smi" else None,
    )

    report = inspect_hf_reasoning_environment(
        Settings(postgres_dsn="postgresql+asyncpg://x")
    )

    assert report.torch_version == "2.12.0+cu130"
    assert report.torch_cuda_built is True
    assert report.cuda_version == "13.0"
    assert report.cuda_available is True
    assert report.cuda_device_count == 1
    assert report.cuda_device_name == "NVIDIA GeForce RTX 4070"
    assert report.torch_cpu_only_with_nvidia_driver is False


def test_hf_reasoning_defaults_are_fast_local_settings() -> None:
    settings = Settings(postgres_dsn="postgresql+asyncpg://x", _env_file=None)

    assert settings.hf_reason_model == "Qwen/Qwen3-0.6B"
    assert settings.hf_reason_max_new_tokens == 512
    assert settings.hf_reason_validation_max_new_tokens == 256
    assert settings.hf_reason_timeout_seconds == 120
    assert settings.hf_reason_answer_mode == "deterministic"
    assert settings.hf_reason_enable_thinking is False


def test_hf_generation_kwargs_include_token_cap_and_timeout() -> None:
    client = HuggingFaceReasoningClient(
        Settings(
            postgres_dsn="postgresql+asyncpg://x",
            hf_reason_max_new_tokens=42,
            hf_reason_timeout_seconds=17,
        )
    )

    kwargs = client._generation_kwargs(FakeHFTokenizer([]), max_new_tokens=42)

    assert kwargs["max_new_tokens"] == 42
    assert kwargs["max_time"] == 17
    assert kwargs["do_sample"] is False


def test_hf_check_reports_dependencies_without_loading_model(monkeypatch) -> None:
    runner = CliRunner()
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://x",
        hf_reason_device="cpu",
        hf_token="hf_test",
    )

    def fail_load_model(self) -> tuple[object, object]:
        raise AssertionError("hf-check should not load the model by default")

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "multi_agentic_rag.llm.hf_reasoning.import_module",
        _fake_hf_importer(),
    )
    monkeypatch.setattr(cli.HuggingFaceReasoningClient, "_load_model", fail_load_model)

    result = runner.invoke(cli.app, ["hf-check"])

    assert result.exit_code == 0
    assert "HF_REASON_MODEL" in result.output
    assert "Qwen/Qwen3-0.6B" in result.output
    assert "HF_REASON_MAX_NEW_TOKENS" in result.output
    assert "512" in result.output
    assert "HF_REASON_VALIDATION_MAX_NEW_TOKENS" in result.output
    assert "256" in result.output
    assert "HF_REASON_TIMEOUT_SECONDS" in result.output
    assert "120" in result.output
    assert "HF_REASON_ANSWER_MODE" in result.output
    assert "deterministic" in result.output
    assert "opt-in with --review-facts" in result.output
    assert "transformers" in result.output
    assert "Model load skipped" in result.output


def test_hf_check_reports_missing_accelerate_without_loading_model(monkeypatch) -> None:
    runner = CliRunner()
    settings = Settings(postgres_dsn="postgresql+asyncpg://x", hf_reason_device="auto")

    def fail_load_model(self) -> tuple[object, object]:
        raise AssertionError("hf-check should not load the model by default")

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "multi_agentic_rag.llm.hf_reasoning.import_module",
        _fake_hf_importer(missing={"accelerate"}),
    )
    monkeypatch.setattr(cli.HuggingFaceReasoningClient, "_load_model", fail_load_model)

    result = runner.invoke(cli.app, ["hf-check"])

    assert result.exit_code == 1
    assert "accelerate" in result.output
    assert 'device_map="auto"' in result.output
    assert "Model load skipped" in result.output


def test_hf_check_reports_cpu_only_torch_on_nvidia_with_gpu_install_hint(monkeypatch) -> None:
    runner = CliRunner()
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://x",
        hf_reason_device="cpu",
        hf_token="hf_test",
    )

    def fail_load_model(self) -> tuple[object, object]:
        raise AssertionError("hf-check should not load the model by default")

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "multi_agentic_rag.llm.hf_reasoning.import_module",
        _fake_hf_importer(),
    )
    monkeypatch.setattr(
        "multi_agentic_rag.llm.hf_reasoning.shutil.which",
        lambda name: "nvidia-smi" if name == "nvidia-smi" else None,
    )
    monkeypatch.setattr(cli.HuggingFaceReasoningClient, "_load_model", fail_load_model)

    result = runner.invoke(cli.app, ["hf-check"])

    assert result.exit_code == 0
    assert "CPU-only" in result.output
    assert "GPU install command" in result.output
    assert "uv sync --dev --extra hf-reasoning --extra gpu" in result.output
    assert "--link-mode=copy" in result.output
    assert "NVIDIA driver detected" in result.output


def test_hf_reasoning_uses_project_cache_dir(tmp_path, monkeypatch) -> None:
    _clear_project_cache_env(monkeypatch)
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://x",
        project_root=tmp_path,
        hf_token="hf_test",
        _env_file=None,
    )
    client = HuggingFaceReasoningClient(settings)

    kwargs = client._hub_kwargs()

    assert kwargs["token"] == "hf_test"
    assert kwargs["cache_dir"] == str(
        tmp_path / ".global_cache" / "models" / "hf_reasoning"
    )
    assert os.environ["HF_HOME"] == str(tmp_path / ".global_cache" / "models" / "huggingface")


def test_reasoning_factory_selects_hf_without_instantiating_openai(monkeypatch) -> None:
    def fail_openai(*args, **kwargs):
        raise AssertionError("OpenAI should not be constructed for hf")

    monkeypatch.setattr("multi_agentic_rag.llm.factory.OpenAIReasoningClient", fail_openai)

    client = build_reasoning_client(
        Settings(postgres_dsn="postgresql+asyncpg://x"),
        "hf",
    )

    assert isinstance(client, HuggingFaceReasoningClient)


def test_openai_quota_error_keeps_cli_hint_markers() -> None:
    with pytest.raises(MultiAgenticRagError) as error:
        asyncio.run(
            OpenAIReasoningClient(
                Settings(postgres_dsn="postgresql+asyncpg://x"),
                client=FakeOpenAIClient(error=FakeOpenAIQuotaError()),
            ).route_intent("ask")
        )

    message = str(error.value)
    assert "HTTP 429" in message
    assert "insufficient_quota" in message
    assert cli._quota_hint_for_message(message) == cli.OPENAI_QUOTA_HINT


def test_answer_builder_hf_does_not_construct_openai(monkeypatch) -> None:
    settings = Settings(postgres_dsn="postgresql+asyncpg://x")
    _patch_hf_reasoning(monkeypatch)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "_build_retriever", lambda settings=None: EvidenceRetriever())

    agent = cli._build_answer_agent("hf")

    assert isinstance(agent.reasoning_client, FakeHFReasoningClient)


def test_user_story_builder_hf_does_not_construct_openai(monkeypatch) -> None:
    settings = Settings(postgres_dsn="postgresql+asyncpg://x")
    _patch_hf_reasoning(monkeypatch)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "_build_retriever", lambda settings=None: EvidenceRetriever())
    monkeypatch.setattr(
        cli.PostgresKnowledgeRepository,
        "from_settings",
        lambda loaded: FakeWorkflowAuditRepository(),
    )
    monkeypatch.setattr(cli, "Neo4jGraphRepository", FakeArtifactGraphRepository)

    agent = cli._build_user_story_agent("hf")

    assert isinstance(agent.reasoning_client, FakeHFReasoningClient)


def test_ingest_command_hf_skips_fact_review_by_default(monkeypatch, tmp_path) -> None:
    settings = Settings(postgres_dsn="postgresql+asyncpg://x")
    source = tmp_path / "brd_v1.md"
    source.write_text("REQ-1 threshold maximum is 80 C.", encoding="utf-8")
    captured_clients: list[object] = []

    def fail_reasoning_client(*args, **kwargs):
        raise AssertionError("ingest should not build a reasoning client by default")

    class CapturingKnowledgeBaseStoringAgent:
        def __init__(self, **kwargs) -> None:
            captured_clients.append(kwargs["fact_review_client"])

        async def ingest(self, *args, **kwargs) -> IngestResult:
            return _ingest_result()

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_reasoning_client", fail_reasoning_client)
    monkeypatch.setattr(cli, "KnowledgeBaseStoringAgent", CapturingKnowledgeBaseStoringAgent)

    cli.ingest(source, system="PROJECT_1", version="v1", kb="default", model="hf")

    assert captured_clients == [None]


def test_ingest_command_hf_review_facts_constructs_hf_reviewer(
    monkeypatch,
    tmp_path,
) -> None:
    settings = Settings(postgres_dsn="postgresql+asyncpg://x")
    source = tmp_path / "brd_v1.md"
    source.write_text("REQ-1 threshold maximum is 80 C.", encoding="utf-8")
    captured_clients: list[object] = []
    _patch_hf_reasoning(monkeypatch)

    class CapturingKnowledgeBaseStoringAgent:
        def __init__(self, **kwargs) -> None:
            captured_clients.append(kwargs["fact_review_client"])

        async def ingest(self, *args, **kwargs) -> IngestResult:
            return _ingest_result()

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "KnowledgeBaseStoringAgent", CapturingKnowledgeBaseStoringAgent)

    cli.ingest(
        source,
        system="PROJECT_1",
        version="v1",
        kb="default",
        model="hf",
        review_facts=True,
    )

    assert isinstance(captured_clients[0], FakeHFReasoningClient)


def test_ingest_directory_hf_review_facts_reuses_one_hf_client_without_openai(
    monkeypatch,
    tmp_path,
) -> None:
    settings = Settings(postgres_dsn="postgresql+asyncpg://x")
    files = [tmp_path / "one_v1.md", tmp_path / "two_v1.md"]
    for path in files:
        path.write_text("REQ-1 threshold maximum is 80 C.", encoding="utf-8")
    captured_clients: list[object] = []
    ingest_calls: list[object] = []
    _patch_hf_reasoning(monkeypatch)

    class CapturingKnowledgeBaseStoringAgent:
        def __init__(self, **kwargs) -> None:
            captured_clients.append(kwargs["fact_review_client"])

        async def ingest(self, *args, **kwargs) -> IngestResult:
            ingest_calls.append(args)
            return _ingest_result()

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "_document_files", lambda directory_path, *, recursive: files)
    monkeypatch.setattr(cli, "KnowledgeBaseStoringAgent", CapturingKnowledgeBaseStoringAgent)

    cli.ingest_directory(
        tmp_path,
        system="PROJECT_1",
        version="v1",
        kb="default",
        model="hf",
        review_facts=True,
    )

    assert len(captured_clients) == 1
    assert isinstance(captured_clients[0], FakeHFReasoningClient)
    assert len(ingest_calls) == 2


def test_ingest_and_user_stories_hf_uses_hf_for_stories_skips_ingest_review_by_default(
    monkeypatch,
    tmp_path,
) -> None:
    settings = Settings(postgres_dsn="postgresql+asyncpg://x")
    source = tmp_path / "brd_v1.md"
    source.write_text("REQ-1 threshold maximum is 80 C.", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeApplication:
        async def ingest_then_user_stories(self, **kwargs):
            captured["scope"] = kwargs
            return (
                type("IngestionResult", (), {"ingest_result": _ingest_result(), "warnings": []})(),
                AgentRunResult(
                    status=AgentRunStatus.SUCCEEDED,
                    artifact_paths=["generated/US-001.yaml"],
                ),
            )

    def fake_build_application(**kwargs) -> FakeApplication:
        captured["model_selector"] = kwargs["model_selector"]
        captured["review_facts"] = kwargs["review_facts"]
        return FakeApplication()

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_application", fake_build_application)

    cli.ingest_and_user_stories(
        source,
        system="PROJECT_1",
        version="v1",
        kb="default",
        model="hf",
    )

    assert captured["model_selector"] == "hf"
    assert captured["review_facts"] is False
    assert captured["scope"] == {
        "document_path": source,
        "system": "PROJECT_1",
        "version": "v1",
        "kb": "default",
    }


def test_ingest_and_user_stories_hf_review_facts_reuses_story_client(
    monkeypatch,
    tmp_path,
) -> None:
    settings = Settings(postgres_dsn="postgresql+asyncpg://x")
    source = tmp_path / "brd_v1.md"
    source.write_text("REQ-1 threshold maximum is 80 C.", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeApplication:
        async def ingest_then_user_stories(self, **kwargs):
            captured["scope"] = kwargs
            return (
                type("IngestionResult", (), {"ingest_result": _ingest_result(), "warnings": []})(),
                AgentRunResult(
                    status=AgentRunStatus.SUCCEEDED,
                    artifact_paths=["generated/US-001.yaml"],
                ),
            )

    def fake_build_application(**kwargs) -> FakeApplication:
        captured["model_selector"] = kwargs["model_selector"]
        captured["review_facts"] = kwargs["review_facts"]
        return FakeApplication()

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_application", fake_build_application)

    cli.ingest_and_user_stories(
        source,
        system="PROJECT_1",
        version="v1",
        kb="default",
        model="hf",
        review_facts=True,
    )

    assert captured["model_selector"] == "hf"
    assert captured["review_facts"] is True
    assert captured["scope"]["document_path"] == source


def test_workflow_builder_hf_does_not_construct_openai(monkeypatch) -> None:
    settings = Settings(postgres_dsn="postgresql+asyncpg://x")
    _patch_hf_reasoning(monkeypatch)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "_build_retriever", lambda settings=None: EvidenceRetriever())
    monkeypatch.setattr(
        cli.PostgresKnowledgeRepository,
        "from_settings",
        lambda loaded: FakeWorkflowAuditRepository(),
    )
    monkeypatch.setattr(cli, "Neo4jGraphRepository", FakeArtifactGraphRepository)

    runner = cli._build_workflow_runner("hf")

    assert isinstance(runner.router.reasoning_client, FakeHFReasoningClient)
    assert runner.planner.reasoning_client is runner.router.reasoning_client
    assert runner.ingest_agent.ingestion_agent.fact_enrichment_agent is None


def test_workflow_builder_passes_hf_client_to_ingest_fact_review(monkeypatch) -> None:
    settings = Settings(postgres_dsn="postgresql+asyncpg://x")
    reasoning_client = FakeReasoningClient()
    captured_ingestion_agents: list[object] = []

    class CapturingKnowledgeBaseStoringAgent:
        def __init__(self, **kwargs) -> None:
            self.fact_review_client = kwargs["fact_review_client"]
            captured_ingestion_agents.append(self)

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_reasoning_client", lambda loaded, selector: reasoning_client)
    monkeypatch.setattr(cli, "KnowledgeBaseStoringAgent", CapturingKnowledgeBaseStoringAgent)
    monkeypatch.setattr(cli, "_build_retriever", lambda settings=None: EvidenceRetriever())
    monkeypatch.setattr(
        cli.PostgresKnowledgeRepository,
        "from_settings",
        lambda loaded: FakeWorkflowAuditRepository(),
    )
    monkeypatch.setattr(cli, "Neo4jGraphRepository", FakeArtifactGraphRepository)

    runner = cli._build_workflow_runner("hf", review_facts=True)

    assert captured_ingestion_agents[0].fact_review_client is reasoning_client
    assert runner.router.reasoning_client is reasoning_client
    assert runner.planner.reasoning_client is reasoning_client
    assert runner.ingest_agent is not None
    assert runner.ingest_agent.ingestion_agent is captured_ingestion_agents[0]


def test_answer_agent_refuses_without_calling_openai() -> None:
    client = FakeReasoningClient()
    result = asyncio.run(
        AgentRetrieveAnswer(EmptyRetriever(), client).run(
            TaskIntent(
                intent_type=TaskIntentType.ANSWER_QUERY,
                system="PROJECT_1",
                kb="default",
            ),
            question="What is the threshold?",
        )
    )

    assert result.status == AgentRunStatus.REFUSED
    assert result.payload["refused"] is True
    assert client.synthesized_questions == []


def test_answer_agent_synthesizes_from_validated_evidence() -> None:
    client = FakeReasoningClient()
    result = asyncio.run(
        AgentRetrieveAnswer(EvidenceRetriever(), client).run(
            TaskIntent(
                intent_type=TaskIntentType.ANSWER_QUERY,
                system="PROJECT_1",
                kb="default",
                version="v1",
            ),
            question="What is the threshold?",
        )
    )

    assert result.status == AgentRunStatus.SUCCEEDED
    assert result.evidence_ids == ["chunk-1"]
    assert result.payload["answer"]["citations"] == ["chunk-1"]
    assert client.synthesized_questions == ["What is the threshold?"]


def test_user_story_builder_writes_yaml_and_debug_json(tmp_path) -> None:
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://x",
        user_story_output_dir=tmp_path / "generated",
    )
    result = asyncio.run(
        AgentUserStoryBuilder(
            EvidenceRetriever(),
            FakeReasoningClient(),
            settings=settings,
        ).run(
            TaskIntent(
                intent_type=TaskIntentType.BUILD_USER_STORIES,
                system="PROJECT_1",
                kb="default",
                version="v1",
            )
        )
    )

    assert result.status == AgentRunStatus.SUCCEEDED
    yaml_path = tmp_path / "generated" / "PROJECT_1" / "default" / "v1" / "user_stories"
    debug_path = tmp_path / "generated" / "PROJECT_1" / "default" / "v1" / "debug"
    assert (yaml_path / "US-001.yaml").exists()
    debug_payload = json.loads((debug_path / "US-001.json").read_text(encoding="utf-8"))
    assert debug_payload["chunk_ids"] == ["chunk-1"]
    assert debug_payload["model"] == "fake-model"


def test_langgraph_runner_executes_composed_ingest_then_user_story_flow() -> None:
    client = FakeReasoningClient(
        routed_intent=TaskIntent(
            intent_type=TaskIntentType.INGEST_THEN_BUILD_USER_STORIES,
            system="PROJECT_1",
            kb="default",
            version="v1",
            documents=["source.md"],
            confidence=1.0,
        )
    )
    state = asyncio.run(
        LangGraphWorkflowRunner(
            router=IntentRouterAgent(client),
            planner=WorkflowPlannerAgent(client),
            validator=FlowValidatorAgent(),
            ingest_agent=FakeIngestAgent(),
            user_story_agent=FakeStoryAgent(),
        ).run(
            "ingest source and write user stories",
            system="PROJECT_1",
            kb="default",
            version="v1",
            documents=["source.md"],
        )
    )

    assert state.status.value == "succeeded"
    assert state.selected_agents == ["AgentIngestDocument", "AgentUserStoryBuilder"]
    assert "ingested" in state.final_response
    assert "story artifact" in state.final_response


def test_langgraph_runner_accepts_descriptive_planner_step_names() -> None:
    client = DescriptivePlanReasoningClient(
        routed_intent=TaskIntent(
            intent_type=TaskIntentType.INGEST_THEN_BUILD_USER_STORIES,
            system="PROJECT_1",
            kb="default",
            version="v1",
            documents=["source.md"],
            confidence=1.0,
        )
    )
    state = asyncio.run(
        LangGraphWorkflowRunner(
            router=IntentRouterAgent(client),
            planner=WorkflowPlannerAgent(client),
            validator=FlowValidatorAgent(),
            ingest_agent=FakeIngestAgent(),
            user_story_agent=FakeStoryAgent(),
        ).run(
            "ingest source and write user stories",
            system="PROJECT_1",
            kb="default",
            version="v1",
            documents=["source.md"],
        )
    )

    assert state.status == WorkflowStatus.SUCCEEDED
    assert "ingested" in state.final_response
    assert "story artifact" in state.final_response


def test_langgraph_runner_turns_openai_route_error_into_failed_state() -> None:
    state = asyncio.run(
        LangGraphWorkflowRunner(
            router=IntentRouterAgent(FailingReasoningClient()),
            planner=WorkflowPlannerAgent(FakeReasoningClient()),
        ).run("ask", system="PROJECT_1")
    )

    assert state.status == WorkflowStatus.FAILED
    assert "OpenAI request failed for task_intent" in state.final_response


def test_default_plan_keeps_future_agents_as_unimplemented_placeholders() -> None:
    plan = default_workflow_plan(
        TaskIntent(
            intent_type=TaskIntentType.TEST_CASE_WRITING,
            system="PROJECT_1",
            kb="default",
            version="v1",
            confidence=1.0,
        )
    )

    assert plan.ordered_agents == []


def test_fact_enrichment_agent_preserves_canonical_fact_and_adds_metadata() -> None:
    fact = _threshold_fact()
    chunk = _chunk_for_fact(fact)

    enriched = asyncio.run(
        FactEnrichmentAgent(FakeFactReviewClient()).enrich(chunks=[chunk], facts=[fact])
    )

    assert enriched[0].fact_id == fact.fact_id
    assert enriched[0].value == fact.value
    assert enriched[0].semantic_key == fact.semantic_key
    assert enriched[0].metadata["llm_review_status"] == "validated"
    assert enriched[0].metadata["llm_canonical_name"] == "temperature-sensor-alpha"
    assert enriched[0].metadata["llm_split_candidates"][0]["canonical_name"] == "temperature"


class FakeReasoningClient:
    model = "fake-model"
    prompt_version = "fake-prompt-v1"

    def __init__(self, routed_intent: TaskIntent | None = None) -> None:
        self.routed_intent = routed_intent
        self.synthesized_questions: list[str] = []

    async def route_intent(self, request: str, *, defaults: dict | None = None) -> TaskIntent:
        if self.routed_intent:
            return self.routed_intent
        return TaskIntent(
            intent_type=TaskIntentType.ANSWER_QUERY,
            system=(defaults or {}).get("system"),
            kb=(defaults or {}).get("kb", "default"),
            version=(defaults or {}).get("version"),
            confidence=1.0,
        )

    async def plan_workflow(self, intent: TaskIntent):
        return default_workflow_plan(intent)

    async def synthesize_answer(self, question: str, evidence) -> GroundedAnswer:
        self.synthesized_questions.append(question)
        return GroundedAnswer(
            answer="The threshold is supported by evidence.",
            citations=evidence.source_chunk_ids,
        )

    async def write_user_stories(self, evidence) -> GeneratedUserStoryBatch:
        return GeneratedUserStoryBatch(
            stories=[
                GeneratedUserStory(
                    id="US-001",
                    title="Monitor temperature threshold",
                    type="functional",
                    domain="industrial",
                    priority="high",
                    status="draft",
                    persona="operator",
                    user_story="As an operator, I want threshold monitoring.",
                    business_value="Prevent unsafe operation.",
                    description="Monitor the documented temperature threshold.",
                    acceptance_criteria=["Given evidence, when threshold is exceeded, then alert."],
                    non_functional_requirements=["Trace every claim to source evidence."],
                    dependencies=[],
                    definition_of_ready=["Evidence is indexed."],
                    definition_of_done=["YAML and debug trace are written."],
                    traceability={"chunk_ids": evidence.source_chunk_ids},
                )
            ]
        )

    async def validate_user_story(
        self,
        story: GeneratedUserStory,
        evidence,
    ) -> QualityValidationReport:
        return QualityValidationReport(status="passed", messages=[], checks={"evidence": True})


class FakeHFReasoningClient(FakeReasoningClient):
    model = "fake-hf-model"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings


class FakeOpenAIClient:
    def __init__(self, payload: dict | None = None, *, error: Exception | None = None) -> None:
        self.responses = FakeResponses(payload or {}, error=error)


class FakeOpenAIQuotaError(Exception):
    status_code = 429
    code = "insufficient_quota"

    def __str__(self) -> str:
        return "quota exceeded"


class FakeResponses:
    def __init__(self, payload: dict, *, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeOpenAIResponse(json.dumps(self.payload))


class FakeOpenAIResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class FakeEncoded(dict):
    def __init__(self) -> None:
        super().__init__({"input_ids": [[1, 2, 3]]})

    def to(self, device: str):
        return self


class LengthEncoded(dict):
    def __init__(self, token_count: int) -> None:
        super().__init__({"input_ids": [list(range(token_count))]})

    def to(self, device: str):
        return self


class FakeHFTokenizer:
    eos_token_id = 0
    pad_token_id = None

    def __init__(self, decoded_outputs: list[dict | str]) -> None:
        self.decoded_outputs = [
            json.dumps(output) if isinstance(output, dict) else output
            for output in decoded_outputs
        ]
        self.user_payloads: list[str] = []
        self.chat_template_calls: list[dict] = []
        self.generate_calls = 0

    def apply_chat_template(self, messages: list[dict], **kwargs) -> str:
        self.chat_template_calls.append(kwargs)
        self.user_payloads.append(str(messages[-1]["content"]))
        return str(messages[-1]["content"])

    def __call__(self, prompts: list[str], *, return_tensors: str) -> FakeEncoded:
        assert prompts
        assert return_tensors == "pt"
        return FakeEncoded()

    def decode(self, output_ids, *, skip_special_tokens: bool) -> str:
        assert skip_special_tokens is True
        self.generate_calls += 1
        return self.decoded_outputs.pop(0)


class CountingHFTokenizer(FakeHFTokenizer):
    def __init__(self, decoded_outputs: list[dict | str], *, token_offset: int = 0) -> None:
        super().__init__(decoded_outputs)
        self.token_offset = token_offset
        self.last_prompt_tokens = 0

    def __call__(self, prompts: list[str], *, return_tensors: str) -> LengthEncoded:
        assert prompts
        assert return_tensors == "pt"
        self.last_prompt_tokens = len(prompts[0].split()) + self.token_offset
        return LengthEncoded(self.last_prompt_tokens)


class FakeHFModel:
    def __init__(self, *, model_window: int = 40960) -> None:
        self.device = "cpu"
        self.config = type("FakeHFConfig", (), {"max_position_embeddings": model_window})()

    def generate(self, **kwargs):
        return [[1, 2, 3, 4]]


class FakeHFCuda:
    def __init__(
        self,
        *,
        available: bool = False,
        count: int = 0,
        device_name: str | None = None,
    ) -> None:
        self.available = available
        self.count = count
        self.device_name = device_name

    def is_available(self) -> bool:
        return self.available

    def device_count(self) -> int:
        return self.count

    def get_device_name(self, index: int) -> str:
        assert index == 0
        return self.device_name or "Fake CUDA Device"


class FakeHFCudaBackend:
    def __init__(self, *, built: bool = False) -> None:
        self.built = built

    def is_built(self) -> bool:
        return self.built


class FakeHFTorchVersion:
    def __init__(self, cuda: str | None = None) -> None:
        self.cuda = cuda


class FakeHFTorchBackends:
    def __init__(self, *, cuda_built: bool = False) -> None:
        self.cuda = FakeHFCudaBackend(built=cuda_built)


class FakeHFTorchModule:
    def __init__(
        self,
        *,
        version: str = "2.6.0+cpu",
        cuda_available: bool = False,
        cuda_version: str | None = None,
        cuda_built: bool = False,
        device_count: int = 0,
        device_name: str | None = None,
    ) -> None:
        self.__version__ = version
        self.cuda = FakeHFCuda(
            available=cuda_available,
            count=device_count,
            device_name=device_name,
        )
        self.version = FakeHFTorchVersion(cuda=cuda_version)
        self.backends = FakeHFTorchBackends(cuda_built=cuda_built)


class FakeHFModule:
    def __init__(self, name: str) -> None:
        self.__version__ = f"{name}-version"


class EmptyRetriever:
    async def retrieve(self, query_text: str, **kwargs) -> list[RetrievalResult]:
        return []


class EvidenceRetriever:
    async def retrieve(self, query_text: str, **kwargs) -> list[RetrievalResult]:
        return [
            RetrievalResult(
                chunk_id="chunk-1",
                document_id="doc-1",
                document_version_id="dv-1",
                system_name="PROJECT_1",
                kb_name="default",
                version="v1",
                source_name="source.md",
                page=1,
                text="REQ-1 temperature threshold maximum is 80 C.",
                score=1.0,
                sources=["bm25"],
            )
        ]


class FakeIngestAgent:
    async def run(self, intent: TaskIntent) -> AgentRunResult:
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            messages=["ingested"],
            payload={"ingest_result": {"document_version_id": "dv-1"}},
        )


class FakeStoryAgent:
    async def run(self, intent: TaskIntent) -> AgentRunResult:
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            messages=["story artifact"],
            evidence_ids=["chunk-1"],
            artifact_paths=["generated/PROJECT_1/default/v1/user_stories/US-001.yaml"],
        )


class FakeWorkflowAuditRepository:
    async def begin_workflow_run(self, run) -> None:
        return None

    async def finish_workflow_run(self, workflow_run_id: str, **kwargs) -> None:
        return None

    async def record_workflow_step(self, step) -> None:
        return None


class FakeArtifactGraphRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def upsert_user_story_artifact(self, **kwargs) -> None:
        return None


class FakeFactReviewClient:
    async def review_facts(self, *, chunk_text: str, facts: list[dict]):
        suggestion = FactEnrichmentSuggestion(
            fact_id=str(facts[0]["fact_id"]),
            fact_key=str(facts[0]["fact_key"]),
            review_status="validated",
            canonical_name="temperature-sensor-alpha",
            relationship_hint="THRESHOLD_FOR",
            split_candidates=[
                FactSplitSuggestion(
                    fact_type="threshold",
                    canonical_name="temperature",
                    value="90 C",
                    relationship_hint="THRESHOLD_FOR",
                    notes="Split the threshold from the sensor label.",
                )
            ],
            uncertain_relationships=["threshold and device relationship"],
            confidence=0.92,
            reasoning_summary="The chunk contains a mixed sensor label and threshold statement.",
        )
        return FactEnrichmentBatch(
            suggestions=[suggestion],
            reasoning_summary="Reviewed one ambiguous fact.",
        )


class FailingReasoningClient(FakeReasoningClient):
    async def route_intent(self, request: str, *, defaults: dict | None = None) -> TaskIntent:
        raise MultiAgenticRagError("OpenAI request failed for task_intent: invalid_json_schema")


class DescriptivePlanReasoningClient(FakeReasoningClient):
    async def plan_workflow(self, intent: TaskIntent) -> WorkflowPlan:
        return WorkflowPlan(
            ordered_agents=[
                "AgentIngestDocument: ingest documents and hand off metadata",
                "AgentUserStoryBuilder: create user stories from evidence",
            ],
            required_tools=["retrieval.hybrid"],
            expected_outputs=["ingest_then_build_user_stories"],
            stop_conditions=["failed_validation"],
        )


def _assert_strict_schema(schema: object) -> None:
    if isinstance(schema, list):
        for item in schema:
            _assert_strict_schema(item)
        return
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties")
    if schema.get("type") == "object" or isinstance(properties, dict):
        assert schema.get("additionalProperties") is False
        assert set(schema.get("required", [])) == set(properties or {})
    for key in ("properties", "$defs", "definitions"):
        children = schema.get(key)
        if isinstance(children, dict):
            for child in children.values():
                _assert_strict_schema(child)
    for key in ("items", "anyOf", "allOf", "oneOf", "not"):
        _assert_strict_schema(schema.get(key))


def _patch_hf_reasoning(monkeypatch) -> None:
    def fail_openai(*args, **kwargs):
        raise AssertionError("OpenAI should not be constructed for hf")

    monkeypatch.setattr("multi_agentic_rag.llm.factory.OpenAIReasoningClient", fail_openai)
    monkeypatch.setattr(
        "multi_agentic_rag.llm.factory.HuggingFaceReasoningClient",
        FakeHFReasoningClient,
    )


def _fake_hf_importer(missing: set[str] | None = None):
    missing_names = missing or set()

    def fake_import_module(name: str):
        if name in missing_names:
            raise ModuleNotFoundError(name)
        return _fake_hf_module(name)

    return fake_import_module


def _fake_hf_module(name: str) -> object:
    if name == "torch":
        return FakeHFTorchModule()
    return FakeHFModule(name)


def _clear_project_cache_env(monkeypatch) -> None:
    for env_name in PROJECT_CACHE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)


def _ingest_result() -> IngestResult:
    return IngestResult(
        document_id="doc-1",
        document_version_id="dv-1",
        chunks_count=1,
        facts_count=1,
        deltas_count=0,
        postgres_status="succeeded",
        chroma_status="indexed:1",
        neo4j_status="projected",
        bm25_status="ready",
        ingestion_run_id="run-1",
        warnings=[],
    )


def _ranked_result(
    text: str,
    *,
    rank: int = 1,
    chunk_id: str = "chunk-1",
    source_name: str = "source.md",
    page: int = 1,
) -> RankedRetrievalResult:
    return RankedRetrievalResult(
        rank=rank,
        evidence_path=["System:PROJECT_1", f"Chunk:{chunk_id}"],
        chunk_id=chunk_id,
        document_id="doc-1",
        document_version_id="dv-1",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        source_name=source_name,
        page=page,
        text=text,
        score=1.0,
        sources=["bm25"],
    )


def _user_story_evidence_bundle(
    *,
    chunk_count: int,
    words_per_chunk: int = 24,
    chunk_prefix: str = "chunk",
    page_offset: int = 0,
) -> EvidenceBundle:
    results = [
        _ranked_result(
            " ".join(
                [f"REQ-{index + 1}", "temperature", "threshold", "maximum", "is", "80", "C."]
                + [f"detail-{index + 1}-{word}" for word in range(words_per_chunk)]
            ),
            rank=index + 1,
            chunk_id=f"{chunk_prefix}-{index + 1}",
            page=page_offset + index + 1,
            source_name="PROJECT_1_BRD_v1.pdf",
        )
        for index in range(chunk_count)
    ]
    chunk_ids = [result.chunk_id for result in results]
    return EvidenceBundle(
        query="Generate implementation-ready user stories for PROJECT_1 v1",
        ranked_results=results,
        source_chunk_ids=chunk_ids,
        graph_paths=[result.evidence_path for result in results],
        version_scope="v1",
    )


def _threshold_fact():
    return FactRecord(
        fact_id="fact-1",
        fact_key="threshold:temperature",
        fact_type="threshold",
        value="90",
        document_version_id="dv-1",
        document_id="doc-1",
        chunk_id="chunk-1",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        status=DocumentStatus.ACTIVE,
        evidence="Temperature sensor Alpha threshold maximum is 90 C and should be monitored.",
        unit="C",
        requirement_id="REQ-1",
        semantic_key="threshold:temperature",
        metadata={"sensor": "temperature"},
    )


def _chunk_for_fact(fact):
    return ChunkRecord(
        chunk_id="chunk-1",
        document_version_id="dv-1",
        document_id="doc-1",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        status=DocumentStatus.ACTIVE,
        source_name="source.md",
        page=1,
        section_title=None,
        chunk_index=0,
        content_hash="hash",
        text="Temperature sensor Alpha threshold maximum is 90 C and should be monitored.",
    )
