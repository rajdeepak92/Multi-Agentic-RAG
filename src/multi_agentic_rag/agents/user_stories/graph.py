"""Compiled LangGraph workflow for user-story generation."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from langgraph.graph import END, START, StateGraph

from multi_agentic_rag.agents.artifacts import UserStoryArtifactWriter
from multi_agentic_rag.agents.user_stories.schemas import (
    EvidenceAssessment,
    EvidenceCandidate,
    RetrievalPlan,
    SourceHit,
    SourceRetrievalResponse,
    UserStoryGenerationRequest,
    UserStoryGenerationResult,
)
from multi_agentic_rag.agents.user_stories.state import UserStoryGenerationState
from multi_agentic_rag.base_operations import create_run_directory, write_json_artifact
from multi_agentic_rag.common import RetrievalSourceName
from multi_agentic_rag.common.logging import configure_command_logging
from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import (
    ArtifactManifest,
    ArtifactRecord,
    EvidenceBundle,
    QualityValidationReport,
    RankedRetrievalResult,
    RetrievalResult,
)
from multi_agentic_rag.exceptions import ConfigError
from multi_agentic_rag.llm import GenerationConfig, ReasoningClient
from multi_agentic_rag.llm.structured import LLMGeneratedUserStoryBatch
from multi_agentic_rag.retrieval.evidence import EvidenceValidator
from multi_agentic_rag.retrieval.reranker import RerankingService
from multi_agentic_rag.runtime.secrets import redact_secrets
from multi_agentic_rag.utils.hashing import stable_id


class Retriever(Protocol):
    """Retriever contract used by each retrieval branch."""

    async def retrieve(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str = "default",
        version: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Retrieve source-specific evidence."""


class ArtifactAuditRepository(Protocol):
    """Optional generated-artifact audit repository."""

    async def record_artifact(self, record: ArtifactRecord) -> None:
        """Persist one artifact audit row."""


class ArtifactGraphRepository(Protocol):
    """Optional graph lineage repository for generated artifacts."""

    def upsert_user_story_artifact(
        self,
        *,
        manifest: ArtifactManifest,
        story_payload: dict[str, Any],
        system_name: str,
        kb_name: str,
        version: str,
    ) -> None:
        """Project generated user-story lineage."""


class UserStoryGraphRuntime:
    """Node implementation for the user-story StateGraph."""

    def __init__(
        self,
        *,
        settings: Settings,
        reasoning_client: ReasoningClient,
        postgres_retriever: Retriever,
        chroma_retriever: Retriever,
        neo4j_retriever: Retriever,
        reranker: RerankingService,
        writer: UserStoryArtifactWriter | None = None,
        artifact_audit_repository: ArtifactAuditRepository | None = None,
        graph_repository: ArtifactGraphRepository | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        self.settings = settings
        self.reasoning_client = reasoning_client
        self.postgres_retriever = postgres_retriever
        self.chroma_retriever = chroma_retriever
        self.neo4j_retriever = neo4j_retriever
        self.reranker = reranker
        self.writer = writer or UserStoryArtifactWriter(settings)
        self.artifact_audit_repository = artifact_audit_repository
        self.graph_repository = graph_repository
        self.log = log or logging.getLogger("multi_agentic_rag.user_stories")
        self.evidence_validator = EvidenceValidator()

    async def validate_request(self, state: UserStoryGenerationState) -> UserStoryGenerationState:
        """Validate scope and create the run directory."""

        try:
            request = UserStoryGenerationRequest.model_validate(state["request"])
            run_id = state.get("run_id")
            run_dir = state.get("run_dir")
            if not run_id or not run_dir:
                run_id, run_dir = create_run_directory(self.settings.user_story_output_dir)
            self.settings.active_run_id = run_id
            self.settings.active_run_dir = run_dir
            self.settings.run_results_dir = run_dir
            self.settings.run_log_path = run_dir / "framework.log"
            configure_command_logging(self.settings.log_level, self.settings.run_log_path)
            return {
                **state,
                "request": request,
                "run_id": run_id,
                "run_dir": run_dir,
                "retrieval_round": state.get("retrieval_round", 0),
                "source_responses": [],
                "artifact_paths": [],
                "errors": [],
                "degraded_sources": [],
                "retry_count": 0,
                "trace_metadata": {
                    "reasoning_provider": self.settings.reasoning_provider,
                    "reasoning_model": self.reasoning_client.model,
                },
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def check_dependencies(self, state: UserStoryGenerationState) -> UserStoryGenerationState:
        """Check configured retrieval source readiness before graph execution."""

        try:
            required_sources = _required_sources(self.settings)
            if RetrievalSourceName.POSTGRES in required_sources:
                repository = getattr(self.postgres_retriever, "repository", None)
                readiness = getattr(repository, "check_readiness", None)
                if readiness is not None:
                    result = await readiness()
                    if not result.ready:
                        raise ConfigError(result.detail)
            for source, retriever in (
                (RetrievalSourceName.CHROMA, self.chroma_retriever),
                (RetrievalSourceName.NEO4J, self.neo4j_retriever),
            ):
                if source not in required_sources:
                    continue
                repository = getattr(retriever, "repository", None) or getattr(
                    retriever,
                    "graph_repository",
                    None,
                )
                check = getattr(repository, "check_connection", None)
                if check is None:
                    continue
                ready, detail = check()
                if not ready:
                    raise ConfigError(detail)
            return state
        except Exception as exc:
            return _state_error(state, exc)

    async def plan_retrieval(self, state: UserStoryGenerationState) -> UserStoryGenerationState:
        """Ask the reasoning provider for source-specific retrieval queries."""

        try:
            if state.get("retrieval_plan") and state.get("next_action") == "refine":
                return {**state, "next_action": ""}
            request = state["request"]
            prompt = _retrieval_plan_prompt(request)
            plan = await _generate_structured_or_default(
                self.reasoning_client,
                prompt=prompt,
                schema=RetrievalPlan,
                generation_config=_generation_config(self.settings, "retrieval_plan"),
                fallback=_default_retrieval_plan(request),
            )
            return {**state, "retrieval_plan": _ensure_non_empty_plan(plan, request)}
        except Exception as exc:
            return _state_error(state, exc)

    async def start_retrieval_round(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Initialize one bounded retrieval round before branch fan-out."""

        return {
            **state,
            "postgres_response": None,  # type: ignore[typeddict-item]
            "chroma_response": None,  # type: ignore[typeddict-item]
            "neo4j_response": None,  # type: ignore[typeddict-item]
        }

    async def retrieve_postgres(
        self,
        state: UserStoryGenerationState,
    ) -> dict[str, SourceRetrievalResponse]:
        """Retrieve PostgreSQL lexical evidence."""

        response = await self._retrieve_source(
            RetrievalSourceName.POSTGRES,
            self.postgres_retriever,
            state,
            _lexical_queries(state["retrieval_plan"], state["request"]),
            self.settings.retrieval_lexical_top_k,
        )
        return {"postgres_response": response}

    async def retrieve_chroma(
        self,
        state: UserStoryGenerationState,
    ) -> dict[str, SourceRetrievalResponse]:
        """Retrieve Chroma semantic evidence."""

        response = await self._retrieve_source(
            RetrievalSourceName.CHROMA,
            self.chroma_retriever,
            state,
            _semantic_queries(state["retrieval_plan"], state["request"]),
            self.settings.retrieval_vector_top_k,
        )
        return {"chroma_response": response}

    async def retrieve_neo4j(
        self,
        state: UserStoryGenerationState,
    ) -> dict[str, SourceRetrievalResponse]:
        """Retrieve Neo4j graph evidence."""

        response = await self._retrieve_source(
            RetrievalSourceName.NEO4J,
            self.neo4j_retriever,
            state,
            _graph_queries(state["retrieval_plan"], state["request"]),
            self.settings.retrieval_graph_top_k,
        )
        return {"neo4j_response": response}

    async def collect_source_results(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Fan-in source responses and enforce degraded retrieval policy."""

        try:
            current = [
                state["postgres_response"],
                state["chroma_response"],
                state["neo4j_response"],
            ]
            required = _required_sources(self.settings)
            errors = list(state.get("errors", []))
            degraded = list(state.get("degraded_sources", []))
            for response in current:
                if response.source not in required:
                    continue
                if response.status == "failed":
                    degraded.append(response.source.value)
                    if not self.settings.retrieval_allow_degraded:
                        errors.append(
                            f"{response.source.value} retrieval failed: "
                            f"{response.error or 'unknown error'}"
                        )
            return {
                **state,
                "source_responses": [*state.get("source_responses", []), *current],
                "degraded_sources": sorted(set(degraded)),
                "errors": errors,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def normalize_candidates(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Normalize source-specific results into provenance-preserving candidates."""

        candidates: list[EvidenceCandidate] = []
        for response in state.get("source_responses", []):
            if response.status not in {"success", "empty"}:
                continue
            for rank, result in enumerate(response.candidates, start=1):
                candidates.append(_candidate_from_result(response, result, rank))
        return {**state, "normalized_candidates": candidates}

    async def deduplicate_candidates(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Merge duplicate evidence while preserving every source hit."""

        merged: dict[str, EvidenceCandidate] = {}
        for candidate in state.get("normalized_candidates", []):
            key = _dedupe_key(candidate)
            existing = merged.get(key)
            if existing is None:
                merged[key] = candidate
                continue
            hits = _merge_source_hits(existing.source_hits, candidate.source_hits)
            metadata = {**existing.metadata, **candidate.metadata}
            requirement_ids = sorted(
                {*existing.requirement_ids, *candidate.requirement_ids}
            )
            entity_ids = sorted({*existing.entity_ids, *candidate.entity_ids})
            merged[key] = existing.model_copy(
                update={
                    "source_hits": hits,
                    "metadata": metadata,
                    "requirement_ids": requirement_ids,
                    "entity_ids": entity_ids,
                }
            )
        return {**state, "deduplicated_candidates": list(merged.values())}

    async def fuse_candidates(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Apply deterministic reciprocal-rank fusion."""

        fusion_k = self.settings.retrieval_reciprocal_rank_constant
        fused: list[EvidenceCandidate] = []
        for candidate in state.get("deduplicated_candidates", []):
            score = sum(1.0 / (fusion_k + hit.rank) for hit in candidate.source_hits)
            score += _graph_signal_boost(candidate)
            sources = {hit.source for hit in candidate.source_hits}
            if RetrievalSourceName.NEO4J in sources and len(sources) > 1:
                score += 0.02
            fused.append(candidate.model_copy(update={"fused_score": score}))
        fused = sorted(
            fused,
            key=lambda item: (-(item.fused_score or 0.0), item.result_id),
        )[: self.settings.retrieval_fusion_top_k]
        return {**state, "fused_results": fused}

    async def rerank_evidence(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Rerank the fused candidate set with the configured reranker."""

        fused = state.get("fused_results", [])
        domain_results = [_candidate_to_domain(candidate) for candidate in fused]
        query = _primary_query(state["retrieval_plan"], state["request"])
        reranked_domain = self.reranker.rerank(query, domain_results)
        by_id = {result.chunk_id: result for result in reranked_domain}
        reranked: list[EvidenceCandidate] = []
        for candidate in fused:
            domain = by_id.get(candidate.chunk_id or candidate.result_id)
            reranker_score = domain.score if domain is not None else candidate.fused_score
            reranked.append(candidate.model_copy(update={"reranker_score": reranker_score}))
        reranked = sorted(
            reranked,
            key=lambda item: (-(item.reranker_score or item.fused_score or 0.0), item.result_id),
        )[: self.settings.retrieval_rerank_top_k]
        ranked = [
            candidate.model_copy(update={"final_rank": index})
            for index, candidate in enumerate(reranked, start=1)
        ]
        return {**state, "reranked_evidence": ranked}

    async def assess_evidence(self, state: UserStoryGenerationState) -> UserStoryGenerationState:
        """Use the reasoning provider to assess evidence sufficiency."""

        try:
            request = state["request"]
            evidence = state.get("reranked_evidence", [])
            if not evidence:
                assessment = EvidenceAssessment(
                    sufficient=False,
                    missing_topics=["traceable evidence"],
                    unsupported_claim_risks=["No retrieved evidence is available."],
                    rationale="No candidates survived retrieval and reranking.",
                )
            else:
                assessment = await _generate_structured_or_default(
                    self.reasoning_client,
                    prompt=_assessment_prompt(request, evidence),
                    schema=EvidenceAssessment,
                    generation_config=_generation_config(self.settings, "evidence_assessment"),
                    fallback=EvidenceAssessment(
                        sufficient=True,
                        covered_requirement_ids=_requirement_ids(evidence),
                        rationale="Compatibility fallback: traceable evidence is present.",
                    ),
                )
            retrieval_round = state.get("retrieval_round", 0)
            if assessment.sufficient:
                return {**state, "evidence_assessment": assessment, "next_action": "sufficient"}
            if (
                assessment.refined_queries is not None
                and retrieval_round < self.settings.retrieval_max_retrieval_rounds
            ):
                return {
                    **state,
                    "evidence_assessment": assessment,
                    "retrieval_plan": assessment.refined_queries,
                    "retrieval_round": retrieval_round + 1,
                    "next_action": "refine",
                }
            if evidence:
                return {
                    **state,
                    "evidence_assessment": assessment,
                    "next_action": "generate_with_gaps",
                }
            return {
                **state,
                "evidence_assessment": assessment,
                "errors": [*state.get("errors", []), "No traceable evidence found."],
                "next_action": "fail",
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def build_prompt(self, state: UserStoryGenerationState) -> UserStoryGenerationState:
        """Build the bounded evidence bundle consumed by story generation."""

        ranked = [
            _candidate_to_ranked_result(candidate)
            for candidate in state.get("reranked_evidence", [])
        ]
        ranked = self.evidence_validator.validate(ranked)
        bundle = EvidenceBundle(
            query=_primary_query(state["retrieval_plan"], state["request"]),
            ranked_results=ranked,
            source_chunk_ids=[result.chunk_id for result in ranked],
            graph_paths=[result.evidence_path for result in ranked],
            version_scope=state["request"].version,
        )
        assessment = state.get("evidence_assessment")
        prompt = json.dumps(
            {
                "schema": "GeneratedUserStoryBatch",
                "evidence_count": len(bundle.ranked_results),
                "source_chunk_ids": bundle.source_chunk_ids,
                "assessment": assessment.model_dump(mode="json") if assessment else {},
            },
            indent=2,
        )
        return {**state, "evidence_bundle": bundle, "prompt": prompt}

    async def generate_structured_output(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Generate structured user stories from validated evidence."""

        try:
            batch_output = await self.reasoning_client.generate_structured(
                prompt=state["prompt"],
                schema=LLMGeneratedUserStoryBatch,
                generation_config=_generation_config(self.settings, "user_story_generation"),
            )
            batch = batch_output.to_domain()
            if not batch.stories:
                raise ConfigError("Reasoning provider returned no user stories.")
            return {**state, "validated_stories": batch.stories}
        except Exception as exc:
            invalid_path = _write_invalid_model_output_if_present(state, exc)
            if invalid_path is not None:
                return _state_error(
                    {**state, "invalid_model_output_path": invalid_path},
                    exc,
                )
            return _state_error(state, exc)

    async def validate_output(self, state: UserStoryGenerationState) -> UserStoryGenerationState:
        """Validate every generated story before YAML publication."""

        try:
            reports: list[QualityValidationReport] = []
            for story in state.get("validated_stories", []):
                reports.append(
                    await self.reasoning_client.validate_user_story(
                        story,
                        state["evidence_bundle"],
                    )
                )
            failures = [
                message
                for report in reports
                if report.status == "failed"
                for message in report.messages
            ]
            retry_allowed = (
                state.get("retry_count", 0) < self.settings.structured_generation_retry_count
            )
            if failures and retry_allowed:
                return {
                    **state,
                    "retry_count": state.get("retry_count", 0) + 1,
                    "errors": [],
                    "next_action": "repair",
                }
            if failures:
                return {**state, "errors": [*state.get("errors", []), *failures]}
            return {**state, "next_action": "valid"}
        except Exception as exc:
            return _state_error(state, exc)

    async def repair_structured_output(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Bounded structured-output repair by regenerating against the same evidence."""

        return await self.generate_structured_output(state)

    async def write_artifacts(self, state: UserStoryGenerationState) -> UserStoryGenerationState:
        """Write YAML and retrieval trace only after validation passes."""

        try:
            request = state["request"]
            paths: list[Path] = []
            for story in state.get("validated_stories", []):
                manifest = self.writer.write(
                    story,
                    system_name=request.system,
                    kb_name=request.kb,
                    version=request.version,
                    evidence=state["evidence_bundle"],
                    model=self.reasoning_client.model,
                    prompt_version=self.reasoning_client.prompt_version,
                    validation_status="passed",
                    validation_messages=[],
                )
                paths.append(Path(manifest.generated_file_path))
                if self.artifact_audit_repository:
                    await self.artifact_audit_repository.record_artifact(
                        ArtifactRecord(
                            artifact_id=manifest.artifact_id,
                            system_name=request.system,
                            kb_name=request.kb,
                            version=request.version,
                            artifact_type="user_story",
                            artifact_path=manifest.generated_file_path,
                            debug_json_path=manifest.debug_json_path,
                            source_chunk_ids=manifest.source_chunk_ids,
                            model=manifest.model,
                            prompt_version=manifest.prompt_version,
                            validation_status=manifest.validation_status,
                        )
                    )
                if self.graph_repository:
                    self.graph_repository.upsert_user_story_artifact(
                        manifest=manifest,
                        story_payload=story.model_dump(mode="json"),
                        system_name=request.system,
                        kb_name=request.kb,
                        version=request.version,
                    )
            trace_path = state["run_dir"] / "debug" / "retrieval_trace.json"
            write_json_artifact(trace_path, redact_secrets(_trace_payload(state)))
            return {
                **state,
                "artifact_paths": paths,
                "debug_trace_path": trace_path,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def finalize_user_stories(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Build the final typed result."""

        errors = state.get("errors", [])
        if errors:
            result = UserStoryGenerationResult(
                status="failed",
                run_id=state.get("run_id", ""),
                messages=errors,
                degraded_sources=[
                    RetrievalSourceName(source) for source in state.get("degraded_sources", [])
                ],
            )
        else:
            result = UserStoryGenerationResult(
                status="succeeded",
                run_id=state["run_id"],
                messages=["Generated user stories."],
                artifact_paths=state.get("artifact_paths", []),
                debug_trace_path=state.get("debug_trace_path"),
                evidence_ids=state.get(
                    "evidence_bundle",
                    EvidenceBundle(query=""),
                ).source_chunk_ids,
                degraded_sources=[
                    RetrievalSourceName(source) for source in state.get("degraded_sources", [])
                ],
                stories=state.get("validated_stories", []),
            )
        return {**state, "result": result}

    async def _retrieve_source(
        self,
        source: RetrievalSourceName,
        retriever: Retriever,
        state: UserStoryGenerationState,
        queries: list[str],
        top_k: int,
    ) -> SourceRetrievalResponse:
        started = time.perf_counter()
        results: list[RetrievalResult] = []
        try:
            for query in queries:
                results.extend(
                    await retriever.retrieve(
                        query,
                        system_name=state["request"].system,
                        kb_name=state["request"].kb,
                        version=state["request"].version,
                        top_k=top_k,
                    )
                )
            duration_ms = int((time.perf_counter() - started) * 1000)
            return SourceRetrievalResponse(
                source=source,
                status="success" if results else "empty",
                queries=queries,
                candidates=results,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return SourceRetrievalResponse(
                source=source,
                status="failed",
                queries=queries,
                duration_ms=duration_ms,
                error=str(exc),
            )


def build_user_story_graph(runtime: UserStoryGraphRuntime) -> Any:
    """Build and compile the mandatory user-story generation StateGraph."""

    graph = StateGraph(UserStoryGenerationState)
    graph.add_node("validate_request", runtime.validate_request)
    graph.add_node("check_dependencies", runtime.check_dependencies)
    graph.add_node("plan_retrieval", runtime.plan_retrieval)
    graph.add_node("start_retrieval_round", runtime.start_retrieval_round)
    graph.add_node("retrieve_postgres", runtime.retrieve_postgres)
    graph.add_node("retrieve_chroma", runtime.retrieve_chroma)
    graph.add_node("retrieve_neo4j", runtime.retrieve_neo4j)
    graph.add_node("collect_source_results", runtime.collect_source_results)
    graph.add_node("normalize_candidates", runtime.normalize_candidates)
    graph.add_node("deduplicate_candidates", runtime.deduplicate_candidates)
    graph.add_node("fuse_candidates", runtime.fuse_candidates)
    graph.add_node("rerank_evidence", runtime.rerank_evidence)
    graph.add_node("assess_evidence", runtime.assess_evidence)
    graph.add_node("build_prompt", runtime.build_prompt)
    graph.add_node("generate_structured_output", runtime.generate_structured_output)
    graph.add_node("validate_output", runtime.validate_output)
    graph.add_node("repair_structured_output", runtime.repair_structured_output)
    graph.add_node("write_artifacts", runtime.write_artifacts)
    graph.add_node("finalize_user_stories", runtime.finalize_user_stories)

    graph.add_edge(START, "validate_request")
    _guarded_edge(graph, "validate_request", "check_dependencies")
    _guarded_edge(graph, "check_dependencies", "plan_retrieval")
    _guarded_edge(graph, "plan_retrieval", "start_retrieval_round")
    graph.add_edge("start_retrieval_round", "retrieve_postgres")
    graph.add_edge("start_retrieval_round", "retrieve_chroma")
    graph.add_edge("start_retrieval_round", "retrieve_neo4j")
    graph.add_edge("retrieve_postgres", "collect_source_results")
    graph.add_edge("retrieve_chroma", "collect_source_results")
    graph.add_edge("retrieve_neo4j", "collect_source_results")
    _guarded_edge(graph, "collect_source_results", "normalize_candidates")
    _guarded_edge(graph, "normalize_candidates", "deduplicate_candidates")
    _guarded_edge(graph, "deduplicate_candidates", "fuse_candidates")
    _guarded_edge(graph, "fuse_candidates", "rerank_evidence")
    _guarded_edge(graph, "rerank_evidence", "assess_evidence")
    graph.add_conditional_edges(
        "assess_evidence",
        _route_after_assessment,
        {
            "build": "build_prompt",
            "refine": "start_retrieval_round",
            "fail": "finalize_user_stories",
        },
    )
    _guarded_edge(graph, "build_prompt", "generate_structured_output")
    _guarded_edge(graph, "generate_structured_output", "validate_output")
    graph.add_conditional_edges(
        "validate_output",
        _route_after_validation,
        {
            "write": "write_artifacts",
            "repair": "repair_structured_output",
            "fail": "finalize_user_stories",
        },
    )
    _guarded_edge(graph, "repair_structured_output", "validate_output")
    _guarded_edge(graph, "write_artifacts", "finalize_user_stories")
    graph.add_edge("finalize_user_stories", END)
    return graph.compile()


def _guarded_edge(graph: Any, source: str, target: str) -> None:
    graph.add_conditional_edges(
        source,
        _route_after_stage,
        {"continue": target, "fail": "finalize_user_stories"},
    )


def _route_after_stage(state: UserStoryGenerationState) -> Literal["continue", "fail"]:
    return "fail" if state.get("errors") else "continue"


def _route_after_assessment(state: UserStoryGenerationState) -> Literal["build", "refine", "fail"]:
    if state.get("errors"):
        return "fail"
    action = state.get("next_action")
    if action == "refine":
        return "refine"
    if action in {"sufficient", "generate_with_gaps"}:
        return "build"
    return "fail"


def _route_after_validation(state: UserStoryGenerationState) -> Literal["write", "repair", "fail"]:
    if state.get("errors"):
        return "fail"
    if state.get("next_action") == "repair":
        return "repair"
    return "write"


def _state_error(state: UserStoryGenerationState, exc: Exception) -> UserStoryGenerationState:
    return {**state, "errors": [*state.get("errors", []), str(exc)]}


def _required_sources(settings: Settings) -> set[RetrievalSourceName]:
    names: set[RetrievalSourceName] = set()
    for source in settings.retrieval_required_sources:
        normalized = str(source).strip().lower()
        names.add(RetrievalSourceName(normalized))
    return names


def _retrieval_plan_prompt(request: UserStoryGenerationRequest) -> str:
    return (
        "Create source-specific retrieval queries for enterprise user-story generation. "
        "Return lexical_queries for PostgreSQL BM25/FTS, semantic_queries for Chroma, "
        "graph_entities and graph_relationships for Neo4j traversal. Do not generate SQL "
        "or Cypher. Scope:\n"
        + json.dumps(request.model_dump(mode="json"), indent=2)
    )


def _assessment_prompt(
    request: UserStoryGenerationRequest,
    evidence: list[EvidenceCandidate],
) -> str:
    payload = {
        "scope": request.model_dump(mode="json"),
        "evidence": [
            {
                "result_id": item.result_id,
                "chunk_id": item.chunk_id,
                "requirement_ids": item.requirement_ids,
                "sources": [hit.source.value for hit in item.source_hits],
                "excerpt": item.text[:800],
            }
            for item in evidence
        ],
    }
    return (
        "Assess whether this evidence is sufficient to generate grounded enterprise "
        "user stories. If insufficient, provide refined retrieval queries. Do not invent "
        "missing requirements.\n"
        + json.dumps(payload, indent=2)
    )


def _generation_config(settings: Settings, task_name: str) -> GenerationConfig:
    return GenerationConfig(
        temperature=0.1,
        max_output_tokens=settings.hf_reason_validation_max_new_tokens
        if task_name == "evidence_assessment"
        else settings.hf_reason_max_new_tokens,
        retry_count=settings.structured_generation_retry_count,
        task_name=task_name,
    )


async def _generate_structured_or_default(
    reasoning_client: ReasoningClient,
    *,
    prompt: str,
    schema: type[Any],
    generation_config: GenerationConfig,
    fallback: Any,
) -> Any:
    method = getattr(reasoning_client, "generate_structured", None)
    if method is None:
        return fallback
    return await method(
        prompt=prompt,
        schema=schema,
        generation_config=generation_config,
    )


def _default_retrieval_plan(request: UserStoryGenerationRequest) -> RetrievalPlan:
    query = (
        "requirements user stories acceptance criteria non functional requirements "
        f"for {request.system} {request.version}"
    )
    return RetrievalPlan(
        lexical_queries=[query],
        semantic_queries=[query],
        graph_entities=[request.system],
        graph_relationships=["requirements", "dependencies", "acceptance criteria"],
        rationale="Deterministic compatibility retrieval plan.",
    )


def _ensure_non_empty_plan(
    plan: RetrievalPlan,
    request: UserStoryGenerationRequest,
) -> RetrievalPlan:
    default = _default_retrieval_plan(request)
    return plan.model_copy(
        update={
            "lexical_queries": plan.lexical_queries or default.lexical_queries,
            "semantic_queries": plan.semantic_queries or default.semantic_queries,
            "graph_entities": plan.graph_entities or default.graph_entities,
            "graph_relationships": plan.graph_relationships or default.graph_relationships,
        }
    )


def _lexical_queries(plan: RetrievalPlan, request: UserStoryGenerationRequest) -> list[str]:
    return plan.lexical_queries or _default_retrieval_plan(request).lexical_queries


def _semantic_queries(plan: RetrievalPlan, request: UserStoryGenerationRequest) -> list[str]:
    return plan.semantic_queries or _default_retrieval_plan(request).semantic_queries


def _graph_queries(plan: RetrievalPlan, request: UserStoryGenerationRequest) -> list[str]:
    queries = [*plan.graph_entities, *plan.graph_relationships, *plan.target_requirement_ids]
    return queries or _default_retrieval_plan(request).semantic_queries


def _primary_query(plan: RetrievalPlan, request: UserStoryGenerationRequest) -> str:
    return (_lexical_queries(plan, request) + _semantic_queries(plan, request))[0]


def _candidate_from_result(
    response: SourceRetrievalResponse,
    result: RetrievalResult,
    rank: int,
) -> EvidenceCandidate:
    metadata = dict(result.metadata)
    hit = SourceHit(
        source=response.source,
        rank=rank,
        raw_score=result.score,
        query=response.queries[0] if response.queries else "",
        evidence_path=_evidence_path(result),
    )
    return EvidenceCandidate(
        result_id=result.chunk_id or stable_id("retrieval_result", result.text[:100], rank),
        document_id=result.document_id or None,
        document_version=result.version or result.document_version_id or None,
        chunk_id=result.chunk_id or None,
        fact_id=_metadata_str(metadata, "fact_id"),
        requirement_ids=_metadata_list(metadata, "requirement_ids", "requirement_id"),
        entity_ids=_metadata_list(metadata, "entity_ids", "entity_id"),
        text=result.text,
        page_number=result.page,
        source_name=result.source_name,
        active_status=_metadata_str(metadata, "status"),
        source_hits=[hit],
        metadata={
            **metadata,
            "document_version_id": result.document_version_id,
            "system_name": result.system_name,
            "kb_name": result.kb_name,
            "sources": result.sources,
        },
    )


def _metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if value not in {None, ""} else None


def _metadata_list(metadata: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value if item not in {None, ""})
        elif value not in {None, ""}:
            values.append(str(value))
    return sorted(set(values))


def _evidence_path(result: RetrievalResult) -> list[str]:
    if not result.chunk_id:
        return []
    return [
        f"System:{result.system_name}",
        f"KnowledgeBase:{result.kb_name}",
        f"Document:{result.document_id}",
        f"DocumentVersion:{result.document_version_id}",
        f"Version:{result.version}",
        f"Chunk:{result.chunk_id}",
        f"Source:{result.source_name}#page={result.page}",
    ]


def _dedupe_key(candidate: EvidenceCandidate) -> str:
    if candidate.chunk_id:
        return f"chunk:{candidate.chunk_id}"
    if candidate.fact_id:
        return f"fact:{candidate.fact_id}"
    if candidate.requirement_ids:
        return "requirement:" + "|".join(candidate.requirement_ids)
    return "semantic:" + stable_id("semantic", candidate.text.strip().lower()[:500])


def _merge_source_hits(
    left: list[SourceHit],
    right: list[SourceHit],
) -> list[SourceHit]:
    merged: dict[tuple[str, int, str], SourceHit] = {}
    for hit in [*left, *right]:
        merged[(hit.source.value, hit.rank, hit.query)] = hit
    return list(merged.values())


def _graph_signal_boost(candidate: EvidenceCandidate) -> float:
    if not any(hit.source == RetrievalSourceName.NEO4J for hit in candidate.source_hits):
        return 0.0
    graph_score = _float_metadata(candidate.metadata.get("graph_score"))
    path_count = _float_metadata(candidate.metadata.get("graph_path_count"))
    return min(graph_score, 6.0) * 0.005 + min(path_count, 5.0) * 0.002


def _float_metadata(value: object) -> float:
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _candidate_to_domain(candidate: EvidenceCandidate) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=candidate.chunk_id or candidate.result_id,
        document_id=candidate.document_id or "",
        document_version_id=str(candidate.metadata.get("document_version_id") or ""),
        system_name=str(candidate.metadata.get("system_name") or ""),
        kb_name=str(candidate.metadata.get("kb_name") or ""),
        version=candidate.document_version or "",
        source_name=candidate.source_name or "",
        page=candidate.page_number or 1,
        text=candidate.text,
        score=candidate.fused_score or 0.0,
        sources=sorted({hit.source.value for hit in candidate.source_hits}),
        metadata=candidate.metadata,
    )


def _candidate_to_ranked_result(candidate: EvidenceCandidate) -> RankedRetrievalResult:
    result = _candidate_to_domain(candidate)
    return RankedRetrievalResult.model_validate(
        {
            **result.model_dump(mode="json"),
            "rank": candidate.final_rank or 0,
            "evidence_path": candidate.source_hits[0].evidence_path
            if candidate.source_hits
            else [],
        }
    )


def _requirement_ids(evidence: list[EvidenceCandidate]) -> list[str]:
    return sorted({item for candidate in evidence for item in candidate.requirement_ids})


def _write_invalid_model_output_if_present(
    state: UserStoryGenerationState,
    exc: Exception,
) -> Path | None:
    raw_output = getattr(exc, "raw_output", None)
    message = str(exc)
    if raw_output is None and "structured output failed validation" not in message.lower():
        return None
    run_dir = state.get("run_dir")
    if run_dir is None:
        return None
    path = run_dir / "debug" / "invalid_model_output.json"
    write_json_artifact(
        path,
        redact_secrets(
            {
                "run_id": state.get("run_id"),
                "stage": "generate_structured_output",
                "error": message,
                "raw_output": raw_output,
                "retry_count": state.get("retry_count", 0),
            }
        ),
    )
    return path


def _trace_payload(state: UserStoryGenerationState) -> dict[str, Any]:
    retrieval_plan = state.get("retrieval_plan")
    evidence_assessment = state.get("evidence_assessment")
    request = state.get("request")
    return {
        "run_id": state.get("run_id"),
        "system": request.system if request else None,
        "version": request.version if request else None,
        "knowledge_base": request.kb if request else None,
        "generated_at": datetime.now(UTC).isoformat(),
        "reasoning_provider": _settings_value(state, "reasoning_provider"),
        "reasoning_model": _settings_value(state, "reasoning_model"),
        "retrieval_plan": retrieval_plan.model_dump(mode="json") if retrieval_plan else None,
        "retrieval_round": state.get("retrieval_round", 0),
        "source_responses": [
            {
                "source": response.source.value,
                "status": response.status,
                "queries": response.queries,
                "query_count": len(response.queries),
                "candidate_count": len(response.candidates),
                "candidates": [
                    {
                        "chunk_id": candidate.chunk_id,
                        "document_id": candidate.document_id,
                        "document_version_id": candidate.document_version_id,
                        "rank": index,
                        "score": candidate.score,
                        "sources": candidate.sources,
                        "graph_paths": candidate.metadata.get("graph_matches", []),
                    }
                    for index, candidate in enumerate(response.candidates, start=1)
                ],
                "duration_ms": response.duration_ms,
                "error": response.error,
            }
            for response in state.get("source_responses", [])
        ],
        "normalization_results": [
            {
                "result_id": candidate.result_id,
                "chunk_id": candidate.chunk_id,
                "source_hits": [hit.model_dump(mode="json") for hit in candidate.source_hits],
            }
            for candidate in state.get("normalized_candidates", [])
        ],
        "deduplicated_candidates": [
            {
                "result_id": candidate.result_id,
                "chunk_id": candidate.chunk_id,
                "document_id": candidate.document_id,
                "requirement_ids": candidate.requirement_ids,
                "entity_ids": candidate.entity_ids,
                "source_hits": [hit.model_dump(mode="json") for hit in candidate.source_hits],
            }
            for candidate in state.get("deduplicated_candidates", [])
        ],
        "fusion_ranks": [
            {
                "result_id": candidate.result_id,
                "chunk_id": candidate.chunk_id,
                "fused_score": candidate.fused_score,
                "source_hits": [hit.model_dump(mode="json") for hit in candidate.source_hits],
            }
            for candidate in state.get("fused_results", [])
        ],
        "reranking_results": [
            {
                "result_id": candidate.result_id,
                "chunk_id": candidate.chunk_id,
                "rank": candidate.final_rank,
                "fused_score": candidate.fused_score,
                "reranker_score": candidate.reranker_score,
                "source_hits": [hit.model_dump(mode="json") for hit in candidate.source_hits],
            }
            for candidate in state.get("reranked_evidence", [])
        ],
        "final_selected_evidence_ids": [
            candidate.chunk_id or candidate.result_id
            for candidate in state.get("reranked_evidence", [])
        ],
        "evidence_assessment": evidence_assessment.model_dump(mode="json")
        if evidence_assessment
        else None,
        "degraded_sources": state.get("degraded_sources", []),
        "validation_retry_count": state.get("retry_count", 0),
        "errors": state.get("errors", []),
    }


def _settings_value(state: UserStoryGenerationState, name: str) -> str | None:
    metadata = state.get("trace_metadata", {})
    if isinstance(metadata, dict):
        value = metadata.get(name)
        return str(value) if value not in {None, ""} else None
    return None
