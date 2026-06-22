from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from multi_agentic_rag.agents.ingestion import IngestionRequest, IngestionResult
from multi_agentic_rag.agents.user_stories import (
    UserStoryGenerationRequest,
    UserStoryGenerationResult,
    UserStoryGraphRuntime,
)
from multi_agentic_rag.agents.user_stories.agent import UserStoryGenerationAgent
from multi_agentic_rag.agents.user_stories.schemas import EvidenceAssessment, RetrievalPlan
from multi_agentic_rag.app import GraphRagApplication
from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import (
    GeneratedUserStory,
    IngestResult,
    QualityValidationReport,
    RetrievalResult,
)
from multi_agentic_rag.exceptions import IngestionError
from multi_agentic_rag.llm import GenerationConfig
from multi_agentic_rag.llm.structured import LLMGeneratedUserStoryBatch
from multi_agentic_rag.retrieval.reranker import NoOpRerankingService


def test_user_story_graph_uses_structured_provider_and_preserves_provenance(
    tmp_path: Path,
) -> None:
    reasoner = FakeStructuredReasoning()
    postgres = FakeRetriever([_retrieval_result("postgres", score=-4.0)])
    chroma = FakeRetriever([_retrieval_result("chroma", score=0.82)])
    neo4j = FakeRetriever([_retrieval_result("neo4j", score=3.0)])
    runtime = _runtime(tmp_path, reasoner, postgres, chroma, neo4j)

    state = asyncio.run(
        UserStoryGenerationAgent(runtime).graph.ainvoke(
            {"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")}
        )
    )

    assert state["result"].status == "succeeded"
    assert reasoner.task_names == [
        "retrieval_plan",
        "evidence_assessment",
        "user_story_generation",
    ]
    responses = {response.source.value: response for response in state["source_responses"]}
    assert {source: response.status for source, response in responses.items()} == {
        "postgres": "success",
        "chroma": "success",
        "neo4j": "success",
    }
    candidate = state["deduplicated_candidates"][0]
    hits = {hit.source.value: hit.raw_score for hit in candidate.source_hits}
    assert hits == {"postgres": -4.0, "chroma": 0.82, "neo4j": 3.0}
    assert state["fused_results"][0].fused_score is not None
    assert state["reranked_evidence"][0].final_rank == 1
    trace = json.loads(state["debug_trace_path"].read_text(encoding="utf-8"))
    assert trace["reasoning_provider"] == "hf"
    assert trace["reasoning_model"] == "fake-structured-model"
    assert {item["status"] for item in trace["source_responses"]} == {"success"}
    assert trace["source_responses"][0]["candidates"][0]["score"] in {-4.0, 0.82, 3.0}
    assert "password" not in state["debug_trace_path"].read_text(encoding="utf-8")
    assert state["artifact_paths"]


def test_user_story_graph_distinguishes_empty_failed_and_degraded_sources(
    tmp_path: Path,
) -> None:
    postgres = FakeRetriever([])
    chroma = FakeRetriever([_retrieval_result("chroma", chunk_id="chunk-2", score=0.7)])
    neo4j = FakeRetriever(error=RuntimeError("neo4j unavailable"))

    failed_state = asyncio.run(
        UserStoryGenerationAgent(
            _runtime(tmp_path / "strict", FakeStructuredReasoning(), postgres, chroma, neo4j)
        ).graph.ainvoke(
            {"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")}
        )
    )

    assert failed_state["result"].status == "failed"
    assert {response.status for response in failed_state["source_responses"]} == {
        "empty",
        "success",
        "failed",
    }
    assert failed_state["artifact_paths"] == []

    degraded_state = asyncio.run(
        UserStoryGenerationAgent(
            _runtime(
                tmp_path / "degraded",
                FakeStructuredReasoning(),
                FakeRetriever([]),
                FakeRetriever([_retrieval_result("chroma", chunk_id="chunk-2", score=0.7)]),
                FakeRetriever(error=RuntimeError("neo4j unavailable")),
                retrieval_allow_degraded=True,
            )
        ).graph.ainvoke(
            {"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")}
        )
    )

    assert degraded_state["result"].status == "succeeded"
    assert degraded_state["result"].degraded_sources[0].value == "neo4j"
    assert degraded_state["artifact_paths"]


def test_structured_repair_is_bounded_and_uses_same_provider(tmp_path: Path) -> None:
    reasoner = FakeStructuredReasoning(validation_statuses=["failed", "passed"])
    runtime = _runtime(
        tmp_path,
        reasoner,
        FakeRetriever([_retrieval_result("postgres")]),
        FakeRetriever([_retrieval_result("chroma")]),
        FakeRetriever([_retrieval_result("neo4j")]),
        structured_generation_retry_count=1,
    )

    state = asyncio.run(
        UserStoryGenerationAgent(runtime).graph.ainvoke(
            {"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")}
        )
    )

    assert state["result"].status == "succeeded"
    assert reasoner.task_names.count("user_story_generation") == 2
    assert state["retry_count"] == 1


def test_retry_exhaustion_does_not_publish_invalid_yaml(tmp_path: Path) -> None:
    reasoner = FakeStructuredReasoning(validation_statuses=["failed", "failed"])
    runtime = _runtime(
        tmp_path,
        reasoner,
        FakeRetriever([_retrieval_result("postgres")]),
        FakeRetriever([_retrieval_result("chroma")]),
        FakeRetriever([_retrieval_result("neo4j")]),
        structured_generation_retry_count=1,
    )

    state = asyncio.run(
        UserStoryGenerationAgent(runtime).graph.ainvoke(
            {"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")}
        )
    )

    assert state["result"].status == "failed"
    assert reasoner.task_names.count("user_story_generation") == 2
    assert state["artifact_paths"] == []
    assert not list((state["run_dir"] / "artifacts" / "user_stories").glob("*.yaml"))


def test_invalid_structured_output_writes_redacted_debug_and_no_yaml(tmp_path: Path) -> None:
    reasoner = FakeStructuredReasoning(
        generation_errors=[
            RawOutputError(
                "structured output failed validation",
                raw_output='{"dsn":"postgresql://user:password@example/db"}',
            )
        ]
    )
    runtime = _runtime(
        tmp_path,
        reasoner,
        FakeRetriever([_retrieval_result("postgres")]),
        FakeRetriever([_retrieval_result("chroma")]),
        FakeRetriever([_retrieval_result("neo4j")]),
    )

    state = asyncio.run(
        UserStoryGenerationAgent(runtime).graph.ainvoke(
            {"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")}
        )
    )

    invalid_path = state["invalid_model_output_path"]
    invalid_text = invalid_path.read_text(encoding="utf-8")
    assert state["result"].status == "failed"
    assert invalid_path.exists()
    assert "password" not in invalid_text
    assert "***" in invalid_text
    assert state["artifact_paths"] == []


def test_application_composition_invokes_two_agents_in_sequence(tmp_path: Path) -> None:
    order: list[str] = []
    ingestion = FakeIngestionAgent(order)
    stories = FakeStoryAgent(order)
    app = GraphRagApplication(
        settings=Settings(postgres_dsn="postgresql+asyncpg://x", _env_file=None),
        reasoning_client=object(),  # type: ignore[arg-type]
        ingestion_agent=ingestion,  # type: ignore[arg-type]
        user_story_agent=stories,  # type: ignore[arg-type]
    )

    asyncio.run(
        app.ingest_then_user_stories(
            document_path=tmp_path / "source.md",
            system="PROJECT_1",
            version="v1",
            kb="default",
        )
    )

    assert order == ["ingest:PROJECT_1:v1:default", "stories:PROJECT_1:v1:default"]

    failing_order: list[str] = []
    failing_app = GraphRagApplication(
        settings=Settings(postgres_dsn="postgresql+asyncpg://x", _env_file=None),
        reasoning_client=object(),  # type: ignore[arg-type]
        ingestion_agent=FakeIngestionAgent(failing_order, fail=True),  # type: ignore[arg-type]
        user_story_agent=FakeStoryAgent(failing_order),  # type: ignore[arg-type]
    )
    with pytest.raises(IngestionError):
        asyncio.run(
            failing_app.ingest_then_user_stories(
                document_path=tmp_path / "source.md",
                system="PROJECT_1",
                version="v1",
                kb="default",
            )
        )
    assert failing_order == ["ingest:PROJECT_1:v1:default"]


class FakeStructuredReasoning:
    model = "fake-structured-model"
    prompt_version = "fake-prompt-v1"

    def __init__(
        self,
        *,
        validation_statuses: list[str] | None = None,
        generation_errors: list[Exception] | None = None,
    ) -> None:
        self.validation_statuses = validation_statuses or ["passed"]
        self.generation_errors = generation_errors or []
        self.task_names: list[str] = []

    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: type[Any],
        generation_config: GenerationConfig,
    ) -> Any:
        self.task_names.append(generation_config.task_name)
        if schema is RetrievalPlan:
            return RetrievalPlan(
                lexical_queries=["requirements user story"],
                semantic_queries=["requirements user story"],
                graph_entities=["PROJECT_1"],
                graph_relationships=["REQUIRES"],
                rationale="test plan",
            )
        if schema is EvidenceAssessment:
            return EvidenceAssessment(
                sufficient=True,
                covered_requirement_ids=["REQ-1"],
                rationale="test evidence is sufficient",
            )
        if schema is LLMGeneratedUserStoryBatch:
            if self.generation_errors:
                raise self.generation_errors.pop(0)
            return LLMGeneratedUserStoryBatch.model_validate(
                {
                    "stories": [
                        {
                            "id": "US-001",
                            "title": "Monitor temperature threshold",
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
                            "definition_of_ready": ["Evidence is indexed."],
                            "definition_of_done": ["Traceability is present."],
                            "traceability": {
                                "chunk_ids": ["chunk-1"],
                                "requirement_ids": ["REQ-1"],
                                "fact_ids": ["fact-1"],
                                "evidence_paths": [["Chunk:chunk-1"]],
                            },
                        }
                    ],
                    "reasoning_summary": "test generation",
                }
            )
        raise AssertionError(schema)

    async def validate_user_story(
        self,
        story: GeneratedUserStory,
        evidence,
    ) -> QualityValidationReport:
        status = self.validation_statuses.pop(0) if self.validation_statuses else "passed"
        return QualityValidationReport(
            status=status,  # type: ignore[arg-type]
            messages=[] if status == "passed" else ["unsupported claim"],
            checks={"evidence": status == "passed"},
        )


class FakeRetriever:
    def __init__(
        self,
        results: list[RetrievalResult] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.results = results or []
        self.error = error
        self.calls: list[str] = []

    async def retrieve(self, query_text: str, **kwargs: Any) -> list[RetrievalResult]:
        self.calls.append(query_text)
        if self.error:
            raise self.error
        return self.results


class RawOutputError(Exception):
    def __init__(self, message: str, *, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output


class FakeIngestionAgent:
    def __init__(self, order: list[str], *, fail: bool = False) -> None:
        self.order = order
        self.fail = fail

    async def run(self, request: IngestionRequest) -> IngestionResult:
        self.order.append(f"ingest:{request.system}:{request.version}:{request.kb}")
        if self.fail:
            raise IngestionError("ingestion failed")
        return IngestionResult(status="succeeded", ingest_result=_ingest_result())


class FakeStoryAgent:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    async def run(self, request: UserStoryGenerationRequest) -> UserStoryGenerationResult:
        self.order.append(f"stories:{request.system}:{request.version}:{request.kb}")
        return UserStoryGenerationResult(status="succeeded", run_id="run-1")


def _runtime(
    tmp_path: Path,
    reasoner: FakeStructuredReasoning,
    postgres: FakeRetriever,
    chroma: FakeRetriever,
    neo4j: FakeRetriever,
    **settings_kwargs: Any,
) -> UserStoryGraphRuntime:
    settings = Settings(
        postgres_dsn="postgresql+asyncpg://x",
        reasoning_provider="hf",
        user_story_output_dir=tmp_path / "generated",
        _env_file=None,
        **settings_kwargs,
    )
    return UserStoryGraphRuntime(
        settings=settings,
        reasoning_client=reasoner,  # type: ignore[arg-type]
        postgres_retriever=postgres,
        chroma_retriever=chroma,
        neo4j_retriever=neo4j,
        reranker=NoOpRerankingService(),
    )


def _retrieval_result(
    source: str,
    *,
    chunk_id: str = "chunk-1",
    score: float = 1.0,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        document_id="doc-1",
        document_version_id="dv-1",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        source_name="source.md",
        page=1,
        text="REQ-1 temperature threshold maximum is 80 C.",
        score=score,
        sources=[source],
        metadata={
            "requirement_ids": ["REQ-1"],
            "fact_id": "fact-1",
            "entity_ids": ["entity-1"],
            "status": "active",
            "graph_matches": [["Requirement:REQ-1", "Chunk:chunk-1"]]
            if source == "neo4j"
            else [],
        },
    )


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
