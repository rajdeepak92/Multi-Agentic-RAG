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
    DocumentStatus,
    GeneratedUserStory,
    IngestResult,
    QualityValidationReport,
    RequirementCoverageRecord,
    RequirementEvidenceRecord,
    RequirementRecord,
    RequirementType,
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
    run_manifest = json.loads(state["run_manifest_path"].read_text(encoding="utf-8"))
    assert trace["reasoning_provider"] == "hf"
    assert trace["reasoning_model"] == "fake-structured-model"
    assert {item["status"] for item in trace["source_responses"]} == {"success"}
    assert trace["source_responses"][0]["candidates"][0]["score"] in {-4.0, 0.82, 3.0}
    assert "password" not in state["debug_trace_path"].read_text(encoding="utf-8")
    assert run_manifest["run_status"] == "succeeded"
    assert run_manifest["publication_status"] == "published"
    assert state["artifact_paths"]
    assert any(Path(path).suffix == ".json" for path in state["artifact_paths"])


def test_user_story_graph_distinguishes_empty_failed_and_degraded_sources(
    tmp_path: Path,
) -> None:
    postgres = FakeRetriever([])
    chroma = FakeRetriever([_retrieval_result("chroma", chunk_id="chunk-2", score=0.7)])
    neo4j = FakeRetriever(error=RuntimeError("neo4j unavailable"))

    failed_state = asyncio.run(
        UserStoryGenerationAgent(
            _runtime(tmp_path / "strict", FakeStructuredReasoning(), postgres, chroma, neo4j)
        ).graph.ainvoke({"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")})
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
        ).graph.ainvoke({"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")})
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
    run_manifest = json.loads(state["run_manifest_path"].read_text(encoding="utf-8"))

    assert state["validation_reports"]
    assert state["validation_failures"] == ["unsupported claim"]
    assert run_manifest["validation_results"]
    assert run_manifest["validation_failures"] == ["unsupported claim"]


def test_user_story_graph_starts_from_requirement_ledger_and_writes_coverage(
    tmp_path: Path,
) -> None:
    repository = FakeRequirementRepository([_requirement_record("REQ-1")])
    runtime = _runtime(
        tmp_path,
        FakeStructuredReasoning(),
        FakeRetriever([_retrieval_result("postgres")]),
        FakeRetriever([_retrieval_result("chroma")]),
        FakeRetriever([_retrieval_result("neo4j")]),
        requirement_repository=repository,
    )

    state = asyncio.run(
        UserStoryGenerationAgent(runtime).graph.ainvoke(
            {"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")}
        )
    )

    assert state["result"].status == "succeeded"
    assert repository.enumerated_scopes == [("PROJECT_1", "default", "v1")]
    assert [requirement.canonical_id for requirement in state["ledger_requirements"]] == ["REQ-1"]
    assert state["coverage_payload"]["counts"] == {"covered": 1}
    assert repository.coverage_records[0].canonical_id == "REQ-1"
    artifact_names = {Path(path).name for path in state["artifact_paths"]}
    assert "requirements_inventory.json" in artifact_names
    assert "requirements_inventory.md" in artifact_names
    assert "requirement_story_coverage.json" in artifact_names
    assert "requirement_story_coverage.csv" in artifact_names


def test_user_story_graph_preserves_all_requirement_evidence(
    tmp_path: Path,
) -> None:
    requirement = _requirement_record("REQ-1")

    repository = FakeRequirementRepository(
        [requirement],
        evidence=[
            RequirementEvidenceRecord(
                requirement_evidence_id="ev-REQ-1-primary",
                requirement_pk=requirement.requirement_pk or "",
                chunk_id="chunk-1",
                document_version_id=requirement.document_version_id,
                source_name="source.md",
                page=1,
                section_title="Requirements",
                start_offset=10,
                end_offset=80,
                evidence_text=("REQ-1 temperature threshold maximum is 80 C."),
            ),
            RequirementEvidenceRecord(
                requirement_evidence_id="ev-REQ-1-secondary",
                requirement_pk=requirement.requirement_pk or "",
                chunk_id="chunk-2",
                document_version_id=requirement.document_version_id,
                source_name="source.md",
                page=2,
                section_title="Threshold Table",
                start_offset=20,
                end_offset=90,
                evidence_text=("Temperature critical level is greater than 80 C."),
            ),
        ],
    )

    runtime = _runtime(
        tmp_path,
        FakeStructuredReasoning(),
        FakeRetriever([_retrieval_result("postgres")]),
        FakeRetriever([_retrieval_result("chroma")]),
        FakeRetriever([_retrieval_result("neo4j")]),
        requirement_repository=repository,
    )

    state = asyncio.run(
        UserStoryGenerationAgent(runtime).graph.ainvoke(
            {
                "request": UserStoryGenerationRequest(
                    system="PROJECT_1",
                    version="v1",
                )
            }
        )
    )

    evidence_entry = state["requirement_evidence_map"]["REQ-1"]

    assert evidence_entry["canonical_id"] == "REQ-1"
    assert evidence_entry["primary_chunk_id"] == "chunk-1"
    assert evidence_entry["source_chunk_ids"] == [
        "chunk-1",
        "chunk-2",
    ]
    assert evidence_entry["source_pages"] == [1, 2]
    assert len(evidence_entry["evidence"]) == 2

    secondary_evidence = evidence_entry["evidence"][1]

    assert secondary_evidence["chunk_id"] == "chunk-2"
    assert secondary_evidence["evidence_text"] == (
        "Temperature critical level is greater than 80 C."
    )
    assert "Requirement:REQ-1" in secondary_evidence["evidence_path"]
    assert "Chunk:chunk-2" in secondary_evidence["evidence_path"]


def test_user_story_graph_blocks_publication_when_required_coverage_is_missing(
    tmp_path: Path,
) -> None:
    repository = FakeRequirementRepository(
        [_requirement_record("REQ-1"), _requirement_record("REQ-2")]
    )
    runtime = _runtime(
        tmp_path,
        FakeStructuredReasoning(),
        FakeRetriever([_retrieval_result("postgres")]),
        FakeRetriever([_retrieval_result("chroma")]),
        FakeRetriever([_retrieval_result("neo4j")]),
        requirement_repository=repository,
        structured_generation_retry_count=0,
    )

    state = asyncio.run(
        UserStoryGenerationAgent(runtime).graph.ainvoke(
            {"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")}
        )
    )

    assert state["result"].status == "failed"
    assert "REQ-2" in state["errors"][0]
    assert state["coverage_payload"]["counts"] == {"covered": 1, "missing": 1}
    assert state["artifact_paths"] == []
    assert repository.coverage_records == []


def test_user_story_graph_generates_in_configured_requirement_batches(
    tmp_path: Path,
) -> None:
    reasoner = BatchAwareStructuredReasoning()
    repository = FakeRequirementRepository(
        [_requirement_record("REQ-1"), _requirement_record("REQ-2")]
    )
    runtime = _runtime(
        tmp_path,
        reasoner,
        FakeRetriever([_retrieval_result("postgres")]),
        FakeRetriever([_retrieval_result("chroma")]),
        FakeRetriever([_retrieval_result("neo4j")]),
        requirement_repository=repository,
        user_story_requirement_batch_size=1,
    )

    state = asyncio.run(
        UserStoryGenerationAgent(runtime).graph.ainvoke(
            {"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")}
        )
    )

    assert state["result"].status == "succeeded"
    assert reasoner.batch_requirement_ids == [["REQ-1"], ["REQ-2"]]
    assert reasoner.task_names.count("user_story_generation") == 2
    assert state["coverage_payload"]["counts"] == {"covered": 2}


def test_user_story_graph_fails_without_fallback_when_structured_generation_fails(
    tmp_path: Path,
) -> None:
    repository = FakeRequirementRepository([_requirement_record("REQ-1")])
    runtime = _runtime(
        tmp_path,
        FakeStructuredReasoning(generation_errors=[RuntimeError("bad json")]),
        FakeRetriever([_retrieval_result("postgres")]),
        FakeRetriever([_retrieval_result("chroma")]),
        FakeRetriever([_retrieval_result("neo4j")]),
        requirement_repository=repository,
    )

    state = asyncio.run(
        UserStoryGenerationAgent(runtime).graph.ainvoke(
            {"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")}
        )
    )

    provider_errors_path = state["provider_errors_path"]
    provider_errors_text = provider_errors_path.read_text(encoding="utf-8")
    run_manifest = json.loads(state["run_manifest_path"].read_text(encoding="utf-8"))
    assert state["result"].status == "failed"
    assert state["failure_error_type"] == "StructuredGenerationError"
    assert "bad json" in state["errors"][0]
    assert "generation_fallback_reason" not in state
    assert "validated_stories" not in state
    assert state["artifact_paths"] == []
    assert repository.coverage_records == []
    assert provider_errors_path.exists()
    assert "StructuredGenerationError" in provider_errors_text
    assert "bad json" in provider_errors_text
    assert run_manifest["run_status"] == "failed"
    assert run_manifest["publication_status"] == "failed"


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


def test_generic_story_language_blocks_publication(tmp_path: Path) -> None:
    repository = FakeRequirementRepository([_requirement_record("BR-001")])
    runtime = _runtime(
        tmp_path,
        GenericStoryReasoning(),
        FakeRetriever([_retrieval_result("postgres")]),
        FakeRetriever([_retrieval_result("chroma")]),
        FakeRetriever([_retrieval_result("neo4j")]),
        requirement_repository=repository,
        structured_generation_retry_count=0,
    )

    state = asyncio.run(
        UserStoryGenerationAgent(runtime).graph.ainvoke(
            {"request": UserStoryGenerationRequest(system="PROJECT_1", version="v1")}
        )
    )

    assert state["result"].status == "failed"
    assert state["failure_error_type"] == "UserStoryQualityError"
    assert "prohibited generic language" in state["errors"][0]
    assert state["artifact_paths"] == []
    assert repository.coverage_records == []


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


class BatchAwareStructuredReasoning(FakeStructuredReasoning):
    def __init__(self) -> None:
        super().__init__()
        self.batch_requirement_ids: list[list[str]] = []

    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: type[Any],
        generation_config: GenerationConfig,
    ) -> Any:
        if schema is not LLMGeneratedUserStoryBatch:
            return await super().generate_structured(
                prompt=prompt,
                schema=schema,
                generation_config=generation_config,
            )
        self.task_names.append(generation_config.task_name)
        payload = json.loads(prompt.split("Batch generation scope:\n", 1)[1])
        requirement_ids = payload["batch_requirement_ids"]
        self.batch_requirement_ids.append(requirement_ids)
        return LLMGeneratedUserStoryBatch.model_validate(
            {
                "stories": [
                    {
                        "id": f"US-{requirement_ids[0]}",
                        "title": f"Cover {requirement_ids[0]}",
                        "type": "functional",
                        "domain": "industrial",
                        "priority": "high",
                        "status": "draft",
                        "persona": "operator",
                        "user_story": f"As an operator, I want {requirement_ids[0]}.",
                        "business_value": "Grounded coverage.",
                        "description": "Generated for one requirement batch.",
                        "acceptance_criteria": ["Given evidence, then cover it."],
                        "non_functional_requirements": [],
                        "dependencies": [],
                        "definition_of_ready": ["Evidence is indexed."],
                        "definition_of_done": ["Traceability is present."],
                        "traceability": {
                            "chunk_ids": ["chunk-1"],
                            "requirement_ids": requirement_ids,
                            "fact_ids": ["fact-1"],
                            "evidence_paths": [["Chunk:chunk-1"]],
                        },
                    }
                ],
                "reasoning_summary": "batch generation",
            }
        )


class GenericStoryReasoning(FakeStructuredReasoning):
    async def generate_structured(
        self,
        *,
        prompt: str,
        schema: type[Any],
        generation_config: GenerationConfig,
    ) -> Any:
        if schema is not LLMGeneratedUserStoryBatch:
            return await super().generate_structured(
                prompt=prompt,
                schema=schema,
                generation_config=generation_config,
            )
        return LLMGeneratedUserStoryBatch.model_validate(
            {
                "stories": [
                    {
                        "id": "US-GENERIC",
                        "title": "Support BR-001",
                        "type": "functional",
                        "domain": "industrial",
                        "priority": "medium",
                        "status": "draft",
                        "persona": "operator",
                        "user_story": (
                            "As an operator, I want the system to satisfy BR-001 "
                            "so that documented business behavior is delivered."
                        ),
                        "business_value": "Provides traceable implementation coverage.",
                        "description": "Implement requirement BR-001.",
                        "acceptance_criteria": ["The feature works as expected."],
                        "non_functional_requirements": [],
                        "dependencies": [],
                        "definition_of_ready": ["Requirement evidence is present."],
                        "definition_of_done": ["Requirement BR-001 is covered."],
                        "traceability": {
                            "chunk_ids": ["chunk-1"],
                            "requirement_ids": ["BR-001"],
                            "fact_ids": [],
                            "evidence_paths": [["Chunk:chunk-1"]],
                        },
                    }
                ],
                "reasoning_summary": "generic story",
            }
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
    requirement_repository: FakeRequirementRepository | None = None,
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
        requirement_repository=requirement_repository,
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
            "graph_matches": [["Requirement:REQ-1", "Chunk:chunk-1"]] if source == "neo4j" else [],
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


class FakeRequirementRepository:
    def __init__(
        self,
        requirements: list[RequirementRecord],
        *,
        evidence: list[RequirementEvidenceRecord] | None = None,
    ) -> None:
        self.requirements = requirements
        self.evidence = evidence
        self.enumerated_scopes: list[tuple[str, str, str]] = []
        self.coverage_records: list[RequirementCoverageRecord] = []

    async def list_requirements_for_scope(
        self,
        *,
        system_name: str,
        kb_name: str,
        version: str,
        **kwargs: Any,
    ) -> list[RequirementRecord]:
        self.enumerated_scopes.append((system_name, kb_name, version))
        return self.requirements

    async def list_requirement_evidence(
        self,
        **kwargs: Any,
    ) -> list[RequirementEvidenceRecord]:
        if self.evidence is not None:
            return self.evidence

        return [
            RequirementEvidenceRecord(
                requirement_evidence_id=f"ev-{requirement.canonical_id}",
                requirement_pk=requirement.requirement_pk or "",
                chunk_id=requirement.chunk_id,
                document_version_id=requirement.document_version_id,
                source_name=requirement.source_name or "source.md",
                page=requirement.page or 1,
                evidence_text=requirement.text,
            )
            for requirement in self.requirements
        ]

    async def upsert_requirement_coverage(
        self,
        records: list[RequirementCoverageRecord],
    ) -> None:
        self.coverage_records.extend(records)


def _requirement_record(canonical_id: str) -> RequirementRecord:
    return RequirementRecord(
        requirement_pk=f"req-{canonical_id}",
        canonical_id=canonical_id,
        requirement_id=canonical_id,
        requirement_type=RequirementType.FUNCTIONAL,
        category="SEN",
        title=canonical_id,
        document_version_id="dv-1",
        document_id="doc-1",
        chunk_id="chunk-1",
        system_name="PROJECT_1",
        kb_name="default",
        version="v1",
        status=DocumentStatus.ACTIVE,
        text=f"{canonical_id} temperature threshold maximum is 80 C.",
        source_name="source.md",
        page=1,
    )
