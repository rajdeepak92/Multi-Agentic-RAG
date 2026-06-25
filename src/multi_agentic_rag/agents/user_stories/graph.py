"""Compiled LangGraph workflow for user-story generation."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

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
    GeneratedUserStory,
    QualityValidationReport,
    RankedRetrievalResult,
    RequirementCoverageRecord,
    RequirementEvidenceRecord,
    RequirementRecord,
    RequirementType,
    RetrievalResult,
)
from multi_agentic_rag.exceptions import (
    ConfigError,
    GenerationTokenLimitError,
    StructuredGenerationError,
    UserStoryGenerationError,
    UserStoryQualityError,
)
from multi_agentic_rag.llm import GenerationConfig, ReasoningClient
from multi_agentic_rag.llm.structured import LLMGeneratedUserStoryBatch
from multi_agentic_rag.requirements_ledger import (
    build_coverage_records,
    coverage_payload,
    requirement_inventory_payload,
    write_coverage_artifacts,
    write_requirement_inventory_artifacts,
)
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


class RequirementLedgerRepository(Protocol):
    """Exact requirement-ledger repository used for story discovery."""

    async def list_requirements_for_scope(
        self,
        *,
        system_name: str,
        kb_name: str,
        version: str,
        requirement_types: set[RequirementType] | None = None,
        active_only: bool = True,
        coverage_required: bool | None = None,
    ) -> list[RequirementRecord]:
        """Return exact requirement records for a scope."""

    async def list_requirement_evidence(
        self,
        *,
        requirement_pks: Sequence[str] | None = None,
    ) -> list[RequirementEvidenceRecord]:
        """Return evidence spans for requirement primary keys."""

    async def upsert_requirement_coverage(
        self,
        records: list[RequirementCoverageRecord],
    ) -> None:
        """Persist requirement-to-story coverage rows."""


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
        requirement_repository: RequirementLedgerRepository | None = None,
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
        self.requirement_repository = requirement_repository
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
            framework_log_path = run_dir / "framework.log"

            self.settings.active_run_id = run_id
            self.settings.active_run_dir = run_dir
            self.settings.run_results_dir = run_dir
            self.settings.run_log_path = framework_log_path

            configure_command_logging(
                self.settings.log_level,
                framework_log_path,
            )

            self.log.info(
                "user_story_run_started run_id=%s system=%s kb=%s version=%s provider=%s model=%s",
                run_id,
                request.system,
                request.kb,
                request.version,
                self.settings.reasoning_provider,
                self.reasoning_client.model,
            )
            return {
                **state,
                "request": request,
                "run_id": run_id,
                "run_dir": run_dir,
                "framework_log_path": (framework_log_path),
                "retrieval_round": state.get(
                    "retrieval_round",
                    0,
                ),
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

    async def enumerate_requirement_ledger(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Enumerate exact active requirements before retrieval enrichment."""

        if self.requirement_repository is None:
            return {
                **state,
                "ledger_requirements": [],
                "ledger_evidence": [],
                "requirement_evidence_map": {},
            }
        try:
            request = state["request"]
            requirements = await self.requirement_repository.list_requirements_for_scope(
                system_name=request.system,
                kb_name=request.kb,
                version=request.version,
                active_only=True,
            )
            evidence = await self.requirement_repository.list_requirement_evidence(
                requirement_pks=[
                    requirement.requirement_pk
                    for requirement in requirements
                    if requirement.requirement_pk
                ]
            )
            requirement_evidence_map = _build_requirement_evidence_map(
                requirements,
                evidence,
            )

            missing_evidence = [
                requirement.canonical_id or requirement.requirement_id
                for requirement in requirements
                if not requirement_evidence_map.get(
                    requirement.canonical_id or requirement.requirement_id,
                    {},
                ).get("source_chunk_ids")
            ]

            if missing_evidence:
                self.log.error(
                    "stage=enumerate_requirement_ledger status=failed missing_evidence=%d",
                    len(missing_evidence),
                )
                return {
                    **state,
                    "ledger_requirements": requirements,
                    "ledger_evidence": evidence,
                    "requirement_evidence_map": requirement_evidence_map,
                    "errors": [
                        *state.get("errors", []),
                        "Requirement ledger has records without evidence: "
                        + ", ".join(missing_evidence[:20]),
                    ],
                }
            self.log.info(
                "stage=enumerate_requirement_ledger "
                "status=succeeded requirements=%d "
                "evidence_rows=%d",
                len(requirements),
                len(evidence),
            )

            return {
                **state,
                "ledger_requirements": requirements,
                "ledger_evidence": evidence,
                "requirement_evidence_map": requirement_evidence_map,
            }
        except Exception as exc:
            return _state_error(state, exc)

    async def plan_retrieval(self, state: UserStoryGenerationState) -> UserStoryGenerationState:
        """Ask the reasoning provider for source-specific retrieval queries."""

        try:
            if state.get("retrieval_plan") and state.get("next_action") == "refine":
                return {**state, "next_action": ""}
            request = state["request"]
            prompt = _retrieval_plan_prompt(request, state.get("ledger_requirements", []))
            plan = await _generate_structured_or_default(
                self.reasoning_client,
                prompt=prompt,
                schema=RetrievalPlan,
                generation_config=_generation_config(self.settings, "retrieval_plan"),
                fallback=_default_retrieval_plan(request),
            )
            return {
                **state,
                "retrieval_plan": _ensure_non_empty_plan(
                    plan,
                    request,
                    state.get("ledger_requirements", []),
                ),
            }
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
            requirement_ids = sorted({*existing.requirement_ids, *candidate.requirement_ids})
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
        reranked_domain = await self.reranker.arerank(
            query,
            domain_results,
        )
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
        ledger_requirements = state.get("ledger_requirements", [])
        story_group_plan = _deterministic_story_group_plan(
            ledger_requirements,
            system=state["request"].system,
            kb=state["request"].kb,
            version=state["request"].version,
            maximum_group_size=self.settings.user_story_maximum_group_size,
        )
        prompt = json.dumps(
            {
                "schema": "GeneratedUserStoryBatch",
                "schema_version": self.settings.user_story_schema_version,
                "scope": state["request"].model_dump(mode="json"),
                "generation_mode": "authoritative_requirement_batches",
                "requirement_batch_size": (self.settings.user_story_requirement_batch_size),
                "max_stories_per_batch": (self.settings.user_story_max_stories_per_batch),
                "allow_partial_coverage": (self.settings.user_story_allow_partial_coverage),
                "coverage_required_types": list(self.settings.user_story_coverage_required_types),
                "generation_contract": {
                    "batch_scoped": True,
                    "requirements_authority": (
                        "The current batch requirement ledger is the complete "
                        "requirement inventory for this generation call."
                    ),
                    "evidence_authority": (
                        "Only source evidence and source chunk IDs supplied in "
                        "the current batch may be cited."
                    ),
                    "requirements": [
                        "Generate stories only for requirements in the current batch.",
                        "Do not use requirements from another batch.",
                        "Do not invent requirement IDs, chunk IDs, facts, or evidence paths.",
                        (
                            "Every generated story must contain non-empty "
                            "traceability.requirement_ids."
                        ),
                        (
                            "Every requirement ID cited by a story must have at least "
                            "one corresponding authorized source chunk in "
                            "traceability.chunk_ids."
                        ),
                        (
                            "Copy evidence paths exactly from the supplied batch "
                            "evidence into traceability.evidence_paths."
                        ),
                    ],
                },
            },
            indent=2,
        )
        return {
            **state,
            "evidence_bundle": bundle,
            "prompt": prompt,
            "story_group_plan": story_group_plan,
        }

    async def generate_structured_output(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Generate stories using isolated authoritative evidence batches."""

        current_batch_index = 0
        current_batch_count = 0
        current_requirement_ids: list[str] = []
        current_source_chunk_ids: list[str] = []

        try:
            request = state["request"]

            story_driving_requirements = [
                requirement
                for requirement in state.get(
                    "ledger_requirements",
                    [],
                )
                if (requirement.story_driving or requirement.coverage_required)
            ]

            batches = (
                list(
                    _batched(
                        story_driving_requirements,
                        self.settings.user_story_requirement_batch_size,
                    )
                )
                if story_driving_requirements
                else [()]
            )
            current_batch_count = len(batches)

            self.log.info(
                "stage=generate_structured_output status=started batches=%d retry_count=%d",
                current_batch_count,
                state.get("retry_count", 0),
            )
            stories: list[GeneratedUserStory] = []
            story_evidence_bundles: dict[str, EvidenceBundle] = {}
            story_batch_requirement_ids: dict[str, list[str]] = {}

            for index, requirement_batch in enumerate(
                batches,
                start=1,
            ):
                if requirement_batch:
                    batch_requirement_ids = [
                        (requirement.canonical_id or requirement.requirement_id)
                        for requirement in requirement_batch
                    ]

                    batch_evidence_bundle = _build_batch_evidence_bundle(
                        requirement_batch,
                        state["requirement_evidence_map"],
                        query=(
                            "Generate grounded user stories for "
                            "requirements: " + ", ".join(batch_requirement_ids)
                        ),
                        version_scope=request.version,
                    )

                    batch_story_group_plan = _deterministic_story_group_plan(
                        list(requirement_batch),
                        system=request.system,
                        kb=request.kb,
                        version=request.version,
                        maximum_group_size=(self.settings.user_story_maximum_group_size),
                    )

                    prompt = _batch_generation_prompt(
                        state["prompt"],
                        requirement_batch,
                        state["requirement_evidence_map"],
                        batch_story_group_plan,
                        batch_index=index,
                        batch_count=len(batches),
                    )
                else:
                    # Compatibility path for workflows without a requirement
                    # repository. Ledger-backed workflows must use the
                    # authoritative batch path above.
                    batch_requirement_ids = []
                    batch_evidence_bundle = state["evidence_bundle"]
                    prompt = state["prompt"]

                current_batch_index = index
                current_requirement_ids = list(batch_requirement_ids)
                current_source_chunk_ids = list(batch_evidence_bundle.source_chunk_ids)

                self.log.info(
                    "stage=generate_structured_output "
                    "status=batch_started "
                    "batch=%d/%d requirements=%d "
                    "source_chunks=%d",
                    index,
                    len(batches),
                    len(batch_requirement_ids),
                    len(batch_evidence_bundle.source_chunk_ids),
                )
                batch_output = await self.reasoning_client.generate_structured(
                    prompt=prompt,
                    schema=LLMGeneratedUserStoryBatch,
                    generation_config=_generation_config(
                        self.settings,
                        "user_story_generation",
                    ),
                )

                batch = batch_output.to_domain()

                if len(batch.stories) > self.settings.user_story_max_stories_per_batch:
                    raise ConfigError(
                        f"Reasoning provider returned more stories than allowed for batch {index}."
                    )
                generation_attempts_path = _write_generation_attempt(
                    state,
                    phase="generation",
                    status="succeeded",
                    batch_index=index,
                    batch_count=len(batches),
                    requirement_ids=(batch_requirement_ids),
                    source_chunk_ids=(batch_evidence_bundle.source_chunk_ids),
                    stories=batch.stories,
                    provider_metadata=(_reasoning_response_metadata(self.reasoning_client)),
                )

                if generation_attempts_path is not None:
                    state = {
                        **state,
                        "generation_attempts_path": (generation_attempts_path),
                    }

                self.log.info(
                    "stage=generate_structured_output "
                    "status=batch_succeeded "
                    "batch=%d/%d stories=%d",
                    index,
                    len(batches),
                    len(batch.stories),
                )
                for story in batch.stories:
                    # _dedupe_stories keeps the first story for a duplicate
                    # ID. setdefault preserves the matching first bundle.
                    story_evidence_bundles.setdefault(
                        story.id,
                        batch_evidence_bundle,
                    )
                    story_batch_requirement_ids.setdefault(
                        story.id,
                        list(batch_requirement_ids),
                    )

                stories.extend(batch.stories)

            if not stories:
                raise ConfigError("Reasoning provider returned no user stories.")

            return {
                **state,
                "validated_stories": _dedupe_stories(stories),
                "story_evidence_bundles": story_evidence_bundles,
                "story_batch_requirement_ids": (story_batch_requirement_ids),
            }

        except Exception as exc:
            generation_attempts_path = _write_generation_attempt(
                state,
                phase="generation",
                status="failed",
                batch_index=(current_batch_index),
                batch_count=(current_batch_count),
                requirement_ids=(current_requirement_ids),
                source_chunk_ids=(current_source_chunk_ids),
                provider_metadata=(_reasoning_response_metadata(self.reasoning_client)),
                error=(f"{type(exc).__name__}: {exc}"),
            )

            if generation_attempts_path is not None:
                state = {
                    **state,
                    "generation_attempts_path": (generation_attempts_path),
                }

            self.log.exception(
                "stage=generate_structured_output status=failed batch=%d/%d",
                current_batch_index,
                current_batch_count,
            )
            typed_error = _generation_error_from_exception(exc)
            invalid_path = _write_invalid_model_output_if_present(
                state,
                exc,
            )
            provider_errors_path = _write_provider_error(
                state,
                typed_error,
                original_exc=exc,
                stage="generate_structured_output",
                provider=self.settings.reasoning_provider,
                deployment=self.reasoning_client.model,
                prompt_version=self.reasoning_client.prompt_version,
                task_name="user_story_generation",
                requested_max_output_tokens=_generation_config(
                    self.settings,
                    "user_story_generation",
                ).max_output_tokens,
                invalid_model_output_path=invalid_path,
            )

            failed_state: UserStoryGenerationState = {
                **state,
                "provider_errors_path": provider_errors_path,
            }

            if invalid_path is not None:
                failed_state = {
                    **failed_state,
                    "invalid_model_output_path": invalid_path,
                }

            return _state_error(
                failed_state,
                typed_error,
                stage="generate_structured_output",
            )

    async def validate_output(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Validate generated stories before publication."""

        try:
            self.log.info(
                "stage=validate_output status=started stories=%d retry_count=%d",
                len(
                    state.get(
                        "validated_stories",
                        [],
                    )
                ),
                state.get("retry_count", 0),
            )
            validated_stories = state.get(
                "validated_stories",
                [],
            )
            ledger_backed = bool(state.get("ledger_requirements"))

            reports_by_story = dict(
                state.get(
                    "validation_reports_by_story",
                    {},
                )
            )
            story_validation_failures: dict[
                str,
                list[str],
            ] = {}

            pending_story_ids = set(
                state.get(
                    "pending_validation_story_ids",
                    [],
                )
            )
            validate_all_stories = not pending_story_ids

            story_evidence_bundles = state.get(
                "story_evidence_bundles",
                {},
            )
            story_batch_requirement_ids = state.get(
                "story_batch_requirement_ids",
                {},
            )
            requirement_evidence_map = state.get(
                "requirement_evidence_map",
                {},
            )

            for story in validated_stories:
                local_failures: list[str] = []

                story_evidence = story_evidence_bundles.get(story.id)

                if ledger_backed:
                    if story_evidence is None:
                        local_failures = [
                            f"Story {story.id}: no authoritative "
                            "evidence bundle is associated with "
                            "the story."
                        ]
                    else:
                        local_failures = _deterministic_traceability_failures(
                            story,
                            allowed_requirement_ids=(
                                story_batch_requirement_ids.get(
                                    story.id,
                                    [],
                                )
                            ),
                            requirement_evidence_map=(requirement_evidence_map),
                            evidence_bundle=story_evidence,
                        )
                else:
                    # Compatibility path for workflows that do not use
                    # the PostgreSQL requirement ledger.
                    story_evidence = story_evidence or state["evidence_bundle"]

                if local_failures:
                    report = _local_traceability_report(local_failures)
                    reports_by_story[story.id] = report
                    story_validation_failures[story.id] = local_failures
                    continue

                if story_evidence is None:
                    local_failures = [
                        f"Story {story.id}: no evidence bundle is available for validation."
                    ]
                    report = _local_traceability_report(local_failures)
                    reports_by_story[story.id] = report
                    story_validation_failures[story.id] = local_failures
                    continue

                should_call_provider = (
                    validate_all_stories
                    or story.id in pending_story_ids
                    or story.id not in reports_by_story
                )

                if should_call_provider:
                    report = await self.reasoning_client.validate_user_story(
                        story,
                        story_evidence,
                    )
                    reports_by_story[story.id] = report
                else:
                    report = reports_by_story[story.id]

                if report.status == "failed":
                    story_validation_failures[story.id] = list(report.messages)

            if self.settings.user_story_fail_on_generic_language:
                for story in validated_stories:
                    generic_failures = _generic_story_failures(story)

                    if not generic_failures:
                        continue

                    story_validation_failures.setdefault(
                        story.id,
                        [],
                    ).extend(generic_failures)

                    existing_report = reports_by_story.get(story.id)

                    existing_messages = list(existing_report.messages) if existing_report else []
                    existing_checks = dict(existing_report.checks) if existing_report else {}

                    existing_checks["generic_language_absent"] = False

                    reports_by_story[story.id] = QualityValidationReport(
                        status="failed",
                        messages=[
                            *existing_messages,
                            *generic_failures,
                        ],
                        checks=existing_checks,
                    )

            reports = [
                reports_by_story[story.id]
                for story in validated_stories
                if story.id in reports_by_story
            ]

            failures = [
                message
                for story_id in sorted(story_validation_failures)
                for message in story_validation_failures[story_id]
            ]

            state = {
                **state,
                "validation_reports": reports,
                "validation_reports_by_story": (reports_by_story),
                "validation_failures": failures,
                "story_validation_failures": (story_validation_failures),
            }

            retry_allowed = (
                state.get("retry_count", 0) < self.settings.structured_generation_retry_count
            )

            if failures and retry_allowed:
                validation_attempts_path = _write_validation_attempt(
                    state,
                    outcome="repair",
                    reports_by_story=(reports_by_story),
                    story_failures=(story_validation_failures),
                )

                retry_state: UserStoryGenerationState = {
                    **state,
                    "retry_count": (state.get("retry_count", 0) + 1),
                    "repair_story_ids": sorted(story_validation_failures),
                    "repair_requirement_ids": [],
                    "pending_validation_story_ids": [],
                    "errors": [],
                    "next_action": "repair",
                }

                if validation_attempts_path is not None:
                    retry_state = {
                        **retry_state,
                        "validation_attempts_path": (validation_attempts_path),
                    }

                self.log.warning(
                    "stage=validate_output status=repair stories=%d failures=%d",
                    len(story_validation_failures),
                    len(failures),
                )

                return retry_state

            if failures:
                validation_attempts_path = _write_validation_attempt(
                    state,
                    outcome="failed",
                    reports_by_story=(reports_by_story),
                    story_failures=(story_validation_failures),
                )

                failed_state = state

                if validation_attempts_path is not None:
                    failed_state = {
                        **failed_state,
                        "validation_attempts_path": (validation_attempts_path),
                    }

                self.log.error(
                    "stage=validate_output status=failed stories=%d failures=%d",
                    len(story_validation_failures),
                    len(failures),
                )

                return _state_error(
                    failed_state,
                    UserStoryQualityError("; ".join(failures[:20])),
                    stage="validate_output",
                )

            ledger_requirements = state.get(
                "ledger_requirements",
                [],
            )

            if ledger_requirements:
                coverage_records = build_coverage_records(
                    requirements=ledger_requirements,
                    story_requirement_ids=(_story_requirement_ids_by_story(validated_stories)),
                )

                matrix = coverage_payload(
                    requirements=ledger_requirements,
                    coverage=coverage_records,
                )

                missing = [
                    row
                    for row in matrix["rows"]
                    if (row["coverage_required"] and row["coverage_status"] == "missing")
                ]

                if missing and retry_allowed:
                    missing_requirement_ids = [str(row["canonical_id"]) for row in missing]
                    coverage_state: UserStoryGenerationState = {
                        **state,
                        "coverage_records": (coverage_records),
                        "coverage_payload": matrix,
                        "retry_count": (
                            state.get(
                                "retry_count",
                                0,
                            )
                            + 1
                        ),
                        "repair_story_ids": [],
                        "repair_requirement_ids": (missing_requirement_ids),
                        "pending_validation_story_ids": [],
                        "errors": [],
                        "next_action": "repair",
                    }

                    validation_attempts_path = _write_validation_attempt(
                        coverage_state,
                        outcome="repair",
                        reports_by_story=(reports_by_story),
                        story_failures={},
                        coverage=matrix,
                    )

                    if validation_attempts_path is not None:
                        coverage_state = {
                            **coverage_state,
                            "validation_attempts_path": (validation_attempts_path),
                        }

                    self.log.warning(
                        "stage=validate_output status=coverage_repair missing_requirements=%d",
                        len(missing_requirement_ids),
                    )

                    return coverage_state
                    # return {
                    #     **state,
                    #     "coverage_records": (coverage_records),
                    #     "coverage_payload": matrix,
                    #     "retry_count": (
                    #         state.get(
                    #             "retry_count",
                    #             0,
                    #         )
                    #         + 1
                    #     ),
                    #     "repair_story_ids": [],
                    #     "repair_requirement_ids": (missing_requirement_ids),
                    #     "pending_validation_story_ids": [],
                    #     "errors": [],
                    #     "next_action": "repair",
                    # }

                if missing and not self.settings.user_story_allow_partial_coverage:
                    missing_ids = ", ".join(str(row["canonical_id"]) for row in missing[:20])
                    failed_state: UserStoryGenerationState = {
                        **state,
                        "coverage_records": (coverage_records),
                        "coverage_payload": matrix,
                    }

                    validation_attempts_path = _write_validation_attempt(
                        failed_state,
                        outcome="failed",
                        reports_by_story=(reports_by_story),
                        story_failures={},
                        coverage=matrix,
                        error=(
                            "Coverage-required requirements are missing stories: " + missing_ids
                        ),
                    )

                    if validation_attempts_path is not None:
                        failed_state = {
                            **failed_state,
                            "validation_attempts_path": (validation_attempts_path),
                        }

                    self.log.error(
                        "stage=validate_output status=coverage_failed missing_requirements=%d",
                        len(missing),
                    )

                    return _state_error(
                        failed_state,
                        UserStoryQualityError(
                            "Coverage-required requirements are missing stories: " + missing_ids
                        ),
                        stage="validate_output",
                    )

                state = {
                    **state,
                    "coverage_records": coverage_records,
                    "coverage_payload": matrix,
                }

            success_state: UserStoryGenerationState = {
                **state,
                "validation_reports": reports,
                "validation_failures": [],
                "story_validation_failures": {},
                "repair_story_ids": [],
                "repair_requirement_ids": [],
                "pending_validation_story_ids": [],
                "next_action": "valid",
            }

            validation_attempts_path = _write_validation_attempt(
                success_state,
                outcome="passed",
                reports_by_story=(reports_by_story),
                story_failures={},
                coverage=cast(
                    dict[str, object],
                    success_state.get(
                        "coverage_payload",
                        {},
                    ),
                ),
            )

            if validation_attempts_path is not None:
                success_state = {
                    **success_state,
                    "validation_attempts_path": (validation_attempts_path),
                }

            self.log.info(
                "stage=validate_output status=passed stories=%d reports=%d",
                len(validated_stories),
                len(reports),
            )

            return success_state

        except Exception as exc:
            validation_attempts_path = _write_validation_attempt(
                state,
                outcome="failed",
                reports_by_story=state.get(
                    "validation_reports_by_story",
                    {},
                ),
                story_failures=state.get(
                    "story_validation_failures",
                    {},
                ),
                coverage=cast(
                    dict[str, object],
                    state.get(
                        "coverage_payload",
                        {},
                    ),
                ),
                error=(f"{type(exc).__name__}: {exc}"),
            )

            failed_state = state

            if validation_attempts_path is not None:
                failed_state = {
                    **failed_state,
                    "validation_attempts_path": (validation_attempts_path),
                }

            self.log.exception("stage=validate_output status=exception")

            return _state_error(
                failed_state,
                exc,
                stage="validate_output",
            )

    async def repair_structured_output(
        self,
        state: UserStoryGenerationState,
    ) -> UserStoryGenerationState:
        """Regenerate only affected requirement batches."""

        current_batch_index = 0
        current_batch_count = 0
        current_requirement_ids: list[str] = []
        current_source_chunk_ids: list[str] = []

        try:
            # Compatibility path for workflows that do not use the
            # PostgreSQL requirement ledger. Without ledger requirements,
            # there is no deterministic requirement batch to target, so
            # perform one bounded full regeneration using the same provider.
            if not state.get("ledger_requirements"):
                return await self.generate_structured_output(
                    {
                        **state,
                        "validation_reports": [],
                        "validation_reports_by_story": {},
                        "validation_failures": [],
                        "story_validation_failures": {},
                        "repair_story_ids": [],
                        "repair_requirement_ids": [],
                        "pending_validation_story_ids": [],
                        "errors": [],
                        "next_action": "",
                    }
                )

            affected_batches = _repair_requirement_batches(
                state,
                batch_size=(self.settings.user_story_requirement_batch_size),
            )
            current_batch_count = len(affected_batches)

            self.log.info(
                "stage=repair_structured_output status=started affected_batches=%d retry_count=%d",
                current_batch_count,
                state.get("retry_count", 0),
            )
            if not affected_batches:
                return _state_error(
                    state,
                    UserStoryQualityError(
                        "Repair was requested but no affected requirement batch could be resolved."
                    ),
                    stage="repair_structured_output",
                )

            affected_requirement_ids = {
                (requirement.canonical_id or requirement.requirement_id)
                for requirement_batch in affected_batches
                for requirement in requirement_batch
            }

            existing_stories = state.get(
                "validated_stories",
                [],
            )
            existing_story_batches = state.get(
                "story_batch_requirement_ids",
                {},
            )

            unaffected_stories = [
                story
                for story in existing_stories
                if not (
                    set(
                        existing_story_batches.get(
                            story.id,
                            [],
                        )
                    )
                    & affected_requirement_ids
                )
            ]

            unaffected_story_ids = {story.id for story in unaffected_stories}

            story_evidence_bundles = {
                story_id: evidence_bundle
                for story_id, evidence_bundle in (
                    state.get(
                        "story_evidence_bundles",
                        {},
                    ).items()
                )
                if story_id in unaffected_story_ids
            }

            story_batch_requirement_ids = {
                story_id: requirement_ids
                for story_id, requirement_ids in (
                    state.get(
                        "story_batch_requirement_ids",
                        {},
                    ).items()
                )
                if story_id in unaffected_story_ids
            }

            repaired_stories: list[GeneratedUserStory] = []
            repaired_story_ids: list[str] = []

            for batch_index, requirement_batch in enumerate(
                affected_batches,
                start=1,
            ):
                batch_requirement_ids = [
                    (requirement.canonical_id or requirement.requirement_id)
                    for requirement in requirement_batch
                ]
                current_batch_index = batch_index
                current_requirement_ids = list(batch_requirement_ids)

                batch_evidence = _build_batch_evidence_bundle(
                    requirement_batch,
                    state["requirement_evidence_map"],
                    query=(
                        "Repair grounded user stories "
                        "for requirements: " + ", ".join(batch_requirement_ids)
                    ),
                    version_scope=(state["request"].version),
                )
                current_source_chunk_ids = list(batch_evidence.source_chunk_ids)

                batch_story_group_plan = _deterministic_story_group_plan(
                    list(requirement_batch),
                    system=(state["request"].system),
                    kb=state["request"].kb,
                    version=(state["request"].version),
                    maximum_group_size=(self.settings.user_story_maximum_group_size),
                )

                prompt = _batch_generation_prompt(
                    state["prompt"],
                    requirement_batch,
                    state["requirement_evidence_map"],
                    batch_story_group_plan,
                    batch_index=batch_index,
                    batch_count=len(affected_batches),
                )

                related_failures = {
                    story_id: messages
                    for story_id, messages in (
                        state.get(
                            "story_validation_failures",
                            {},
                        ).items()
                    )
                    if (
                        set(
                            state.get(
                                "story_batch_requirement_ids",
                                {},
                            ).get(story_id, [])
                        )
                        & set(batch_requirement_ids)
                    )
                }

                repair_context = {
                    "repair_attempt": state.get(
                        "retry_count",
                        0,
                    ),
                    "requirements_to_repair": (batch_requirement_ids),
                    "previous_validation_failures": (related_failures),
                    "allowed_source_chunk_ids": (batch_evidence.source_chunk_ids),
                    "instruction": (
                        "Regenerate only this requirement "
                        "batch. Correct every listed "
                        "traceability failure. Use only "
                        "the supplied requirement IDs, "
                        "authorized chunk IDs, and exact "
                        "evidence paths."
                    ),
                }

                prompt += "\n\nRepair context:\n" + json.dumps(
                    repair_context,
                    indent=2,
                )

                batch_output = await self.reasoning_client.generate_structured(
                    prompt=prompt,
                    schema=(LLMGeneratedUserStoryBatch),
                    generation_config=(
                        _generation_config(
                            self.settings,
                            "user_story_generation",
                        )
                    ),
                )

                batch = batch_output.to_domain()

                if not batch.stories:
                    raise ConfigError(
                        "Repair provider returned no "
                        "stories for requirements: " + ", ".join(batch_requirement_ids)
                    )

                if len(batch.stories) > self.settings.user_story_max_stories_per_batch:
                    raise ConfigError(
                        "Repair provider returned more "
                        "stories than allowed for batch "
                        f"{batch_index}."
                    )
                generation_attempts_path = _write_generation_attempt(
                    state,
                    phase="repair",
                    status="succeeded",
                    batch_index=batch_index,
                    batch_count=len(affected_batches),
                    requirement_ids=(batch_requirement_ids),
                    source_chunk_ids=(batch_evidence.source_chunk_ids),
                    stories=batch.stories,
                    provider_metadata=(_reasoning_response_metadata(self.reasoning_client)),
                )

                if generation_attempts_path is not None:
                    state = {
                        **state,
                        "generation_attempts_path": (generation_attempts_path),
                    }

                self.log.info(
                    "stage=repair_structured_output status=batch_succeeded batch=%d/%d stories=%d",
                    batch_index,
                    len(affected_batches),
                    len(batch.stories),
                )
                for story in batch.stories:
                    repaired_stories.append(story)
                    repaired_story_ids.append(story.id)

                    story_evidence_bundles[story.id] = batch_evidence

                    story_batch_requirement_ids[story.id] = list(batch_requirement_ids)

            combined_stories = _dedupe_stories(
                [
                    *unaffected_stories,
                    *repaired_stories,
                ]
            )

            retained_story_ids = {story.id for story in combined_stories}
            repaired_story_id_set = set(repaired_story_ids)

            reports_by_story = {
                story_id: report
                for story_id, report in (
                    state.get(
                        "validation_reports_by_story",
                        {},
                    ).items()
                )
                if (story_id in retained_story_ids and story_id not in repaired_story_id_set)
            }

            return {
                **state,
                "validated_stories": combined_stories,
                "story_evidence_bundles": (story_evidence_bundles),
                "story_batch_requirement_ids": (story_batch_requirement_ids),
                "validation_reports_by_story": (reports_by_story),
                "validation_reports": list(reports_by_story.values()),
                "validation_failures": [],
                "story_validation_failures": {},
                "repair_story_ids": [],
                "repair_requirement_ids": [],
                "pending_validation_story_ids": (sorted(repaired_story_id_set)),
                "errors": [],
                "next_action": "",
            }

        except Exception as exc:
            generation_attempts_path = _write_generation_attempt(
                state,
                phase="repair",
                status="failed",
                batch_index=(current_batch_index),
                batch_count=(current_batch_count),
                requirement_ids=(current_requirement_ids),
                source_chunk_ids=(current_source_chunk_ids),
                provider_metadata=(_reasoning_response_metadata(self.reasoning_client)),
                error=(f"{type(exc).__name__}: {exc}"),
            )

            failed_state = state

            if generation_attempts_path is not None:
                failed_state = {
                    **failed_state,
                    "generation_attempts_path": (generation_attempts_path),
                }

            self.log.exception(
                "stage=repair_structured_output status=failed batch=%d/%d",
                current_batch_index,
                current_batch_count,
            )

            return _state_error(
                failed_state,
                exc,
                stage="repair_structured_output",
            )

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
                    evidence=state.get(
                        "story_evidence_bundles",
                        {},
                    ).get(
                        story.id,
                        state["evidence_bundle"],
                    ),
                    model=self.reasoning_client.model,
                    prompt_version=self.reasoning_client.prompt_version,
                    validation_status="passed",
                    validation_messages=[],
                )
                paths.append(Path(manifest.generated_file_path))
                paths.append(Path(manifest.generated_file_path).with_suffix(".json"))
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
            artifact_dir = state["run_dir"] / "artifacts" / "user_stories"
            ledger_requirements = state.get("ledger_requirements", [])
            if ledger_requirements:
                story_group_plan = state.get("story_group_plan", [])
                if story_group_plan:
                    story_group_path = artifact_dir / "story_group_plan.json"
                    write_json_artifact(story_group_path, {"groups": story_group_plan})
                    paths.append(story_group_path)
                inventory_payload = requirement_inventory_payload(
                    ledger_requirements,
                    state.get("ledger_evidence", []),
                    system_name=request.system,
                    kb_name=request.kb,
                    version=request.version,
                )
                paths.extend(
                    write_requirement_inventory_artifacts(
                        output_dir=artifact_dir,
                        payload=inventory_payload,
                    )
                )
                coverage_records = state.get("coverage_records", [])
                coverage_matrix = state.get("coverage_payload")
                if coverage_matrix:
                    paths.extend(
                        write_coverage_artifacts(
                            output_dir=artifact_dir,
                            payload=coverage_matrix,
                        )
                    )
                if self.requirement_repository and coverage_records:
                    await self.requirement_repository.upsert_requirement_coverage(coverage_records)
            quality_paths = _write_story_quality_artifacts(
                artifact_dir,
                state.get("validated_stories", []),
                state.get("validation_reports", []),
                state.get("coverage_payload", {}),
            )
            paths.extend(quality_paths)
            generation_trace_path = state["run_dir"] / "debug" / "generation_trace.json"
            validation_trace_path = state["run_dir"] / "debug" / "validation_trace.json"
            write_json_artifact(
                generation_trace_path,
                redact_secrets(
                    {
                        "run_id": state.get("run_id"),
                        "provider": self.settings.reasoning_provider,
                        "deployment": self.reasoning_client.model,
                        "prompt_version": self.reasoning_client.prompt_version,
                        "retry_count": state.get("retry_count", 0),
                        "story_count": len(state.get("validated_stories", [])),
                        "story_group_plan": state.get("story_group_plan", []),
                    }
                ),
            )
            write_json_artifact(
                validation_trace_path,
                redact_secrets(
                    {
                        "run_id": state.get("run_id"),
                        "reports": [
                            report.model_dump(mode="json")
                            for report in state.get("validation_reports", [])
                        ],
                        "coverage": state.get("coverage_payload", {}),
                    }
                ),
            )
            trace_path = state["run_dir"] / "debug" / "retrieval_trace.json"
            write_json_artifact(trace_path, redact_secrets(_trace_payload(state)))
            self.log.info(
                "stage=write_artifacts status=succeeded stories=%d paths=%d",
                len(
                    state.get(
                        "validated_stories",
                        [],
                    )
                ),
                len(paths),
            )
            return {
                **state,
                "artifact_paths": paths,
                "debug_trace_path": trace_path,
                "generation_trace_path": generation_trace_path,
                "validation_trace_path": validation_trace_path,
            }
        except Exception as exc:
            self.log.exception("stage=write_artifacts status=failed")
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
            coverage_summary = _coverage_summary_message(state)
            result = UserStoryGenerationResult(
                status="succeeded",
                run_id=state["run_id"],
                messages=["Generated user stories.", coverage_summary],
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
        self.log.info(
            "stage=finalize_user_stories status=%s run_id=%s artifacts=%d errors=%d",
            result.status,
            result.run_id,
            len(result.artifact_paths),
            len(errors),
        )
        manifest_path = _write_run_manifest(state, result)
        return {**state, "result": result, "run_manifest_path": manifest_path}

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

            self.log.info(
                "stage=retrieve_%s status=%s candidates=%d duration_ms=%d",
                source.value,
                "success" if results else "empty",
                len(results),
                duration_ms,
            )

            return SourceRetrievalResponse(
                source=source,
                status="success" if results else "empty",
                queries=queries,
                candidates=results,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)

            self.log.info(
                "stage=retrieve_%s status=%s candidates=%d duration_ms=%d",
                source.value,
                "success" if results else "empty",
                len(results),
                duration_ms,
            )

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
    graph.add_node("enumerate_requirement_ledger", runtime.enumerate_requirement_ledger)
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
    _guarded_edge(graph, "check_dependencies", "enumerate_requirement_ledger")
    _guarded_edge(graph, "enumerate_requirement_ledger", "plan_retrieval")
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


def _state_error(
    state: UserStoryGenerationState,
    exc: Exception,
    *,
    stage: str | None = None,
) -> UserStoryGenerationState:
    message = f"{type(exc).__name__}: {exc}"
    return {
        **state,
        "errors": [*state.get("errors", []), message],
        "failure_error_type": type(exc).__name__,
        **({"failure_stage": stage} if stage else {}),
    }


def _required_sources(settings: Settings) -> set[RetrievalSourceName]:
    names: set[RetrievalSourceName] = set()
    for source in settings.retrieval_required_sources:
        normalized = str(source).strip().lower()
        names.add(RetrievalSourceName(normalized))
    return names


def _retrieval_plan_prompt(
    request: UserStoryGenerationRequest,
    requirements: list[RequirementRecord] | None = None,
) -> str:
    requirement_context = [
        {
            "canonical_id": requirement.canonical_id or requirement.requirement_id,
            "requirement_type": requirement.requirement_type.value,
            "category": requirement.category,
            "text": requirement.text[:400],
        }
        for requirement in requirements or []
        if requirement.story_driving or requirement.coverage_required
    ]
    return (
        "Create source-specific retrieval queries for enterprise user-story generation. "
        "Return lexical_queries for PostgreSQL BM25/FTS, semantic_queries for Chroma, "
        "graph_entities and graph_relationships for Neo4j traversal. Do not generate SQL "
        "or Cypher. Use the provided requirement ledger as the complete inventory; do not "
        "use retrieval to decide which requirements exist.\n"
        + json.dumps(
            {
                "scope": request.model_dump(mode="json"),
                "requirement_ledger": requirement_context,
            },
            indent=2,
        )
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
        "missing requirements.\n" + json.dumps(payload, indent=2)
    )


def _generation_config(settings: Settings, task_name: str) -> GenerationConfig:
    return GenerationConfig(
        temperature=settings.hf_reason_temperature,
        max_output_tokens=settings.hf_reason_validation_max_new_tokens
        if task_name == "evidence_assessment"
        else settings.hf_reason_max_new_tokens,
        retry_count=settings.structured_generation_retry_count,
        task_name=task_name,
    )


def _build_requirement_evidence_map(
    requirements: Sequence[RequirementRecord],
    evidence: Sequence[RequirementEvidenceRecord],
) -> dict[str, dict[str, Any]]:
    """Build the authoritative requirement-to-source-evidence mapping.

    The requirement ledger remains the authoritative inventory, while
    RequirementEvidenceRecord rows provide the complete source lineage for
    every requirement. Multiple evidence rows and chunks are preserved.
    """

    evidence_by_requirement_pk: dict[str, list[RequirementEvidenceRecord]] = {}

    for evidence_record in evidence:
        evidence_by_requirement_pk.setdefault(
            evidence_record.requirement_pk,
            [],
        ).append(evidence_record)

    requirement_evidence_map: dict[str, dict[str, Any]] = {}

    sorted_requirements = sorted(
        requirements,
        key=lambda requirement: (
            requirement.canonical_id or requirement.requirement_id,
            requirement.requirement_pk or "",
        ),
    )

    for requirement in sorted_requirements:
        canonical_id = requirement.canonical_id or requirement.requirement_id
        requirement_pk = requirement.requirement_pk or ""

        evidence_records = sorted(
            evidence_by_requirement_pk.get(requirement_pk, []),
            key=lambda evidence_record: (
                evidence_record.page,
                evidence_record.chunk_id,
                evidence_record.requirement_evidence_id,
            ),
        )

        evidence_payloads: list[dict[str, Any]] = []

        for evidence_record in evidence_records:
            evidence_payloads.append(
                {
                    "requirement_evidence_id": (evidence_record.requirement_evidence_id),
                    "chunk_id": evidence_record.chunk_id,
                    "document_version_id": (evidence_record.document_version_id),
                    "source_name": evidence_record.source_name,
                    "page": evidence_record.page,
                    "section_title": evidence_record.section_title,
                    "start_offset": evidence_record.start_offset,
                    "end_offset": evidence_record.end_offset,
                    "evidence_text": evidence_record.evidence_text,
                    "extraction_method": (evidence_record.extraction_method),
                    "confidence": evidence_record.confidence,
                    "evidence_path": [
                        f"System:{requirement.system_name}",
                        f"KnowledgeBase:{requirement.kb_name}",
                        f"Document:{requirement.document_id}",
                        (f"DocumentVersion:{evidence_record.document_version_id}"),
                        f"Version:{requirement.version}",
                        f"Requirement:{canonical_id}",
                        f"Chunk:{evidence_record.chunk_id}",
                        (f"Source:{evidence_record.source_name}#page={evidence_record.page}"),
                    ],
                }
            )

        requirement_evidence_map[canonical_id] = {
            "requirement_pk": requirement.requirement_pk,
            "canonical_id": canonical_id,
            "requirement_id": requirement.requirement_id,
            "requirement_type": requirement.requirement_type.value,
            "category": requirement.category,
            "title": requirement.title,
            "text": requirement.text,
            "coverage_required": requirement.coverage_required,
            "story_driving": requirement.story_driving,
            "document_id": requirement.document_id,
            "document_version_id": requirement.document_version_id,
            "version": requirement.version,
            "source_name": requirement.source_name,
            "source_page": requirement.page,
            "primary_chunk_id": requirement.chunk_id,
            "source_chunk_ids": sorted(
                {evidence_record.chunk_id for evidence_record in evidence_records}
            ),
            "source_pages": sorted({evidence_record.page for evidence_record in evidence_records}),
            "evidence": evidence_payloads,
        }

    return requirement_evidence_map


def _build_batch_evidence_bundle(
    requirements: Sequence[RequirementRecord],
    requirement_evidence_map: dict[str, dict[str, Any]],
    *,
    query: str,
    version_scope: str,
) -> EvidenceBundle:
    """Build authoritative evidence for one requirement generation batch.

    Evidence rows are grouped by source chunk. A chunk shared by multiple
    requirements is represented once, with all associated requirement IDs
    preserved in metadata.
    """

    chunk_payloads: dict[str, dict[str, Any]] = {}

    for requirement in requirements:
        canonical_id = requirement.canonical_id or requirement.requirement_id
        evidence_entry = requirement_evidence_map.get(canonical_id)

        if not evidence_entry:
            raise ConfigError(
                f"No authoritative evidence mapping exists for requirement {canonical_id}."
            )

        evidence_rows = evidence_entry.get("evidence", [])

        if not isinstance(evidence_rows, list) or not evidence_rows:
            raise ConfigError(
                f"No authoritative evidence rows exist for requirement {canonical_id}."
            )

        for evidence_row in evidence_rows:
            if not isinstance(evidence_row, dict):
                continue

            chunk_id = str(evidence_row.get("chunk_id") or "").strip()
            if not chunk_id:
                continue

            page = evidence_row.get("page")
            if not isinstance(page, int) or page < 1:
                page = requirement.page or 1

            source_name = str(
                evidence_row.get("source_name") or requirement.source_name or ""
            ).strip()

            if not source_name:
                raise ConfigError(
                    f"Authoritative evidence has no source name for requirement {canonical_id}."
                )

            chunk_payload = chunk_payloads.setdefault(
                chunk_id,
                {
                    "document_id": requirement.document_id,
                    "document_version_id": str(
                        evidence_row.get("document_version_id") or requirement.document_version_id
                    ),
                    "system_name": requirement.system_name,
                    "kb_name": requirement.kb_name,
                    "version": requirement.version,
                    "source_name": source_name,
                    "page": page,
                    "texts": [],
                    "requirement_ids": set(),
                    "requirement_evidence_ids": set(),
                },
            )

            evidence_text = str(evidence_row.get("evidence_text") or requirement.text).strip()

            texts = cast(list[str], chunk_payload["texts"])
            if evidence_text and evidence_text not in texts:
                texts.append(evidence_text)

            cast(
                set[str],
                chunk_payload["requirement_ids"],
            ).add(canonical_id)

            requirement_evidence_id = str(evidence_row.get("requirement_evidence_id") or "").strip()

            if requirement_evidence_id:
                cast(
                    set[str],
                    chunk_payload["requirement_evidence_ids"],
                ).add(requirement_evidence_id)

    if requirements and not chunk_payloads:
        requirement_ids = ", ".join(
            requirement.canonical_id or requirement.requirement_id for requirement in requirements
        )
        raise ConfigError(
            "No authoritative source chunks could be built for requirement "
            f"batch: {requirement_ids}"
        )

    retrieval_results: list[RetrievalResult] = []

    ordered_chunks = sorted(
        chunk_payloads.items(),
        key=lambda item: (
            int(item[1]["page"]),
            item[0],
        ),
    )

    for chunk_id, payload in ordered_chunks:
        retrieval_results.append(
            RetrievalResult(
                chunk_id=chunk_id,
                document_id=str(payload["document_id"]),
                document_version_id=str(payload["document_version_id"]),
                system_name=str(payload["system_name"]),
                kb_name=str(payload["kb_name"]),
                version=str(payload["version"]),
                source_name=str(payload["source_name"]),
                page=int(payload["page"]),
                text="\n".join(cast(list[str], payload["texts"])),
                score=1.0,
                sources=["requirement_ledger"],
                metadata={
                    "authoritative_requirement_evidence": True,
                    "requirement_ids": sorted(
                        cast(
                            set[str],
                            payload["requirement_ids"],
                        )
                    ),
                    "requirement_evidence_ids": sorted(
                        cast(
                            set[str],
                            payload["requirement_evidence_ids"],
                        )
                    ),
                },
            )
        )

    ranked_results = EvidenceValidator().validate(retrieval_results)

    if len(ranked_results) != len(retrieval_results):
        raise ConfigError(
            "One or more authoritative requirement evidence chunks failed lineage validation."
        )

    return EvidenceBundle(
        query=query,
        ranked_results=ranked_results,
        source_chunk_ids=[result.chunk_id for result in ranked_results],
        graph_paths=[result.evidence_path for result in ranked_results],
        version_scope=version_scope,
    )


def _story_driving_requirement_payloads(
    requirements: list[RequirementRecord],
) -> list[dict[str, Any]]:
    return [
        _requirement_prompt_payload(requirement)
        for requirement in requirements
        if requirement.story_driving or requirement.coverage_required
    ]


def _deterministic_story_group_plan(
    requirements: list[RequirementRecord],
    *,
    system: str,
    kb: str,
    version: str,
    maximum_group_size: int,
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], list[RequirementRecord]] = {}
    for requirement in requirements:
        if not requirement.story_driving and not requirement.coverage_required:
            continue
        key = (
            requirement.category or "uncategorized",
            requirement.requirement_type.value,
            requirement.section_title or "unknown-section",
        )
        grouped.setdefault(key, []).append(requirement)
    plans: list[dict[str, object]] = []
    for (category, requirement_type, section), records in sorted(grouped.items()):
        records = sorted(
            records,
            key=lambda item: item.canonical_id or item.requirement_id,
        )
        for index, batch in enumerate(_batched(records, max(1, maximum_group_size)), start=1):
            requirement_ids = [record.canonical_id or record.requirement_id for record in batch]
            group_id = (
                "GROUP-"
                + stable_id(
                    "story_group",
                    system,
                    kb,
                    version,
                    category,
                    requirement_type,
                    section,
                    str(index),
                    *requirement_ids,
                )[-12:].upper()
            )
            plans.append(
                {
                    "group_id": group_id,
                    "title": f"{category} {requirement_type} capability",
                    "persona": _persona_hint(batch),
                    "business_outcome": _business_outcome_hint(batch),
                    "requirement_ids": requirement_ids,
                    "requirement_pks": [record.requirement_pk for record in batch],
                    "grouping_rationale": (
                        "Grouped deterministically by category, requirement type, "
                        "source section and version scope."
                    ),
                    "cohesion_score": 0.8 if len(batch) > 1 else 1.0,
                    "grouping_method": "deterministic",
                    "source_section": section,
                }
            )
    return plans


def _persona_hint(records: Sequence[RequirementRecord]) -> str | None:
    for record in records:
        persona = record.metadata.get("persona") or record.metadata.get("stakeholder")
        if isinstance(persona, str) and persona.strip():
            return persona.strip()
    return None


def _business_outcome_hint(records: Sequence[RequirementRecord]) -> str | None:
    for record in records:
        outcome = record.metadata.get("business_outcome")
        if isinstance(outcome, str) and outcome.strip():
            return outcome.strip()
    first = next(iter(records), None)
    if first is None:
        return None
    return first.title or first.category or first.requirement_type.value


def _requirement_prompt_payload(
    requirement: RequirementRecord,
    evidence_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one batch-scoped requirement and evidence payload."""

    authoritative_evidence = evidence_entry or {}

    source_chunk_ids = authoritative_evidence.get(
        "source_chunk_ids",
        [requirement.chunk_id],
    )
    source_pages = authoritative_evidence.get(
        "source_pages",
        [requirement.page] if requirement.page is not None else [],
    )
    source_evidence = authoritative_evidence.get("evidence", [])

    return {
        "canonical_id": (requirement.canonical_id or requirement.requirement_id),
        "requirement_type": requirement.requirement_type.value,
        "category": requirement.category,
        "title": requirement.title,
        "text": requirement.text,
        "coverage_required": requirement.coverage_required,
        "story_driving": requirement.story_driving,
        "primary_source_chunk_id": requirement.chunk_id,
        "source_chunk_ids": list(source_chunk_ids),
        "source_pages": list(source_pages),
        "source_evidence": list(source_evidence),
    }


def _batched(
    requirements: list[RequirementRecord],
    batch_size: int,
) -> list[tuple[RequirementRecord, ...]]:
    effective_size = max(1, batch_size)
    return [
        tuple(requirements[index : index + effective_size])
        for index in range(0, len(requirements), effective_size)
    ]


def _batch_generation_prompt(
    base_prompt: str,
    requirements: tuple[RequirementRecord, ...],
    requirement_evidence_map: dict[str, dict[str, Any]],
    story_group_plan: list[dict[str, object]],
    *,
    batch_index: int,
    batch_count: int,
) -> str:
    """Build one isolated requirement-batch generation prompt."""

    if not requirements:
        return base_prompt

    batch_requirement_ids = [
        requirement.canonical_id or requirement.requirement_id for requirement in requirements
    ]

    missing_evidence = [
        requirement_id
        for requirement_id in batch_requirement_ids
        if not requirement_evidence_map.get(
            requirement_id,
            {},
        ).get("source_chunk_ids")
    ]

    if missing_evidence:
        raise ConfigError(
            "Cannot generate user stories without authoritative evidence for: "
            + ", ".join(missing_evidence)
        )

    batch_requirements = [
        _requirement_prompt_payload(
            requirement,
            requirement_evidence_map[requirement.canonical_id or requirement.requirement_id],
        )
        for requirement in requirements
    ]

    allowed_source_chunk_ids = sorted(
        {
            chunk_id
            for requirement in batch_requirements
            for chunk_id in requirement["source_chunk_ids"]
        }
    )

    payload = {
        "batch_index": batch_index,
        "batch_count": batch_count,
        "batch_requirement_ids": batch_requirement_ids,
        "allowed_source_chunk_ids": allowed_source_chunk_ids,
        "batch_requirements": batch_requirements,
        "batch_story_group_plan": story_group_plan,
        "traceability_contract": {
            "allowed_requirement_ids": batch_requirement_ids,
            "allowed_source_chunk_ids": allowed_source_chunk_ids,
            "rules": [
                (
                    "For each acceptance criterion, add one claims entry with "
                    "claim_type='acceptance_criterion', the criterion index, "
                    "the exact criterion text, related requirement IDs, authorized "
                    "chunk IDs, and copied evidence paths."
                ),
                (
                    "Add claims entries for the user_story, business_value, "
                    "description, non-functional requirements, definition of ready, "
                    "and definition of done when those fields contain source-grounded claims."
                ),
                (
                    "The aggregate traceability requirement_ids, chunk_ids, and "
                    "evidence_paths must contain the union of all claims entries."
                ),
                (
                    "Each generated story must cite only requirement IDs "
                    "listed in allowed_requirement_ids."
                ),
                (
                    "Each requirement ID in traceability.requirement_ids "
                    "must be linked to at least one of its supplied "
                    "source_chunk_ids."
                ),
                (
                    "traceability.chunk_ids must contain only IDs listed "
                    "in allowed_source_chunk_ids."
                ),
                (
                    "traceability.evidence_paths must be copied exactly "
                    "from batch_requirements.source_evidence.evidence_path."
                ),
                ("Do not generate stories for requirements outside this batch."),
            ],
        },
        "instruction": (
            "Generate only user stories grounded in this isolated batch. "
            "Every coverage-required batch requirement must be covered or "
            "explicitly deferred with a reason. Do not use requirements, "
            "chunk IDs, or evidence from any other batch."
        ),
    }

    return base_prompt + "\n\nBatch generation scope:\n" + json.dumps(payload, indent=2)


def _dedupe_stories(stories: list[GeneratedUserStory]) -> list[GeneratedUserStory]:
    deduped: dict[str, GeneratedUserStory] = {}
    for story in stories:
        deduped.setdefault(story.id, story)
    return list(deduped.values())


_GENERIC_STORY_PATTERNS = (
    "support br-",
    "satisfy br-",
    "implement requirement",
    "meet the documented requirement",
    "documented business behavior",
    "traceable implementation coverage",
    "feature works as expected",
    "works as expected",
    "system shall support the requirement",
    "system to satisfy",
)


def _traceability_string_list(
    traceability: dict[str, Any],
    key: str,
) -> list[str]:
    """Return one normalized unique string list from traceability."""

    value = traceability.get(key, [])

    if not isinstance(value, list):
        return []

    normalized: list[str] = []

    for item in value:
        text = str(item).strip()

        if text and text not in normalized:
            normalized.append(text)

    return normalized


def _traceability_paths(
    traceability: dict[str, Any],
) -> list[list[str]]:
    """Return valid normalized traceability evidence paths."""

    value = traceability.get("evidence_paths", [])

    if not isinstance(value, list):
        return []

    normalized_paths: list[list[str]] = []

    for path in value:
        if not isinstance(path, list):
            continue

        normalized_path = [str(item).strip() for item in path if str(item).strip()]

        if normalized_path:
            normalized_paths.append(normalized_path)

    return normalized_paths


def _path_contains(
    paths: Sequence[Sequence[str]],
    expected: str,
) -> bool:
    """Return whether at least one path contains the expected node."""

    return any(expected in path for path in paths)


def _claim_traceability_failures(
    story: GeneratedUserStory,
    *,
    allowed_requirement_ids: Sequence[str],
    requirement_evidence_map: dict[str, dict[str, Any]],
) -> list[str]:
    """Validate optional claim-level traceability entries."""

    traceability = story.traceability

    if not isinstance(traceability, dict):
        return []

    claims = traceability.get("claims", [])

    # Claims remain optional for backward compatibility.
    if not claims:
        return []

    if not isinstance(claims, list):
        return [f"Story {story.id}: traceability.claims must be a list."]

    failures: list[str] = []
    allowed_requirement_set = set(allowed_requirement_ids)

    for claim_index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            failures.append(
                f"Story {story.id}: traceability claim {claim_index} must be an object."
            )
            continue

        claim_text = str(claim.get("claim_text") or "").strip()

        if not claim_text:
            failures.append(
                f"Story {story.id}: traceability claim {claim_index} has empty claim_text."
            )

        raw_requirement_ids = claim.get(
            "requirement_ids",
            [],
        )
        raw_chunk_ids = claim.get("chunk_ids", [])

        if not isinstance(raw_requirement_ids, list):
            raw_requirement_ids = []

        if not isinstance(raw_chunk_ids, list):
            raw_chunk_ids = []

        claim_requirement_ids = {
            str(item).strip() for item in raw_requirement_ids if str(item).strip()
        }
        claim_chunk_ids = {str(item).strip() for item in raw_chunk_ids if str(item).strip()}

        if not claim_requirement_ids:
            failures.append(
                f"Story {story.id}: traceability claim {claim_index} has no requirement IDs."
            )
            continue

        out_of_batch = sorted(claim_requirement_ids - allowed_requirement_set)

        if out_of_batch:
            failures.append(
                f"Story {story.id}: traceability claim "
                f"{claim_index} contains out-of-batch "
                "requirements: " + ", ".join(out_of_batch)
            )

        for requirement_id in claim_requirement_ids:
            evidence_entry = requirement_evidence_map.get(requirement_id)

            if evidence_entry is None:
                failures.append(
                    f"Story {story.id}: traceability claim "
                    f"{claim_index} references unknown "
                    f"requirement {requirement_id}."
                )
                continue

            authorized_chunks = {
                str(chunk_id).strip()
                for chunk_id in evidence_entry.get(
                    "source_chunk_ids",
                    [],
                )
                if str(chunk_id).strip()
            }

            if not claim_chunk_ids & authorized_chunks:
                failures.append(
                    f"Story {story.id}: traceability claim "
                    f"{claim_index} for requirement "
                    f"{requirement_id} has no authorized "
                    "source chunk."
                )

    return failures


def _deterministic_traceability_failures(
    story: GeneratedUserStory,
    *,
    allowed_requirement_ids: Sequence[str],
    requirement_evidence_map: dict[str, dict[str, Any]],
    evidence_bundle: EvidenceBundle,
) -> list[str]:
    """Validate story traceability without calling an LLM."""

    failures: list[str] = []
    traceability = story.traceability

    if not isinstance(traceability, dict):
        return [f"Story {story.id}: traceability must be an object."]

    requirement_ids = _traceability_string_list(
        traceability,
        "requirement_ids",
    )
    chunk_ids = _traceability_string_list(
        traceability,
        "chunk_ids",
    )
    evidence_paths = _traceability_paths(traceability)

    allowed_requirement_set = set(allowed_requirement_ids)
    allowed_bundle_chunks = set(evidence_bundle.source_chunk_ids)

    if not requirement_ids:
        failures.append(f"Story {story.id}: traceability.requirement_ids is empty.")

    if not chunk_ids:
        failures.append(f"Story {story.id}: traceability.chunk_ids is empty.")

    if not evidence_paths:
        failures.append(f"Story {story.id}: traceability.evidence_paths is empty.")

    unknown_requirements = sorted(set(requirement_ids) - allowed_requirement_set)

    if unknown_requirements:
        failures.append(
            f"Story {story.id}: requirement IDs are outside "
            "its generation batch: " + ", ".join(unknown_requirements) + "."
        )

    unknown_chunks = sorted(set(chunk_ids) - allowed_bundle_chunks)

    if unknown_chunks:
        failures.append(
            f"Story {story.id}: chunk IDs are not authorized "
            "for its generation batch: " + ", ".join(unknown_chunks) + "."
        )

    for requirement_id in requirement_ids:
        evidence_entry = requirement_evidence_map.get(requirement_id)

        if evidence_entry is None:
            failures.append(
                f"Story {story.id}: requirement "
                f"{requirement_id} does not exist in the "
                "authoritative requirement map."
            )
            continue

        authorized_chunks = {
            str(chunk_id).strip()
            for chunk_id in evidence_entry.get(
                "source_chunk_ids",
                [],
            )
            if str(chunk_id).strip()
        }

        cited_authorized_chunks = sorted(authorized_chunks & set(chunk_ids))

        if not cited_authorized_chunks:
            expected = ", ".join(sorted(authorized_chunks)) or "<none>"

            failures.append(
                f"Story {story.id}: requirement "
                f"{requirement_id} has no authorized source "
                "chunk citation. Expected one of: "
                f"{expected}."
            )
            continue

        requirement_path_node = f"Requirement:{requirement_id}"

        if not _path_contains(
            evidence_paths,
            requirement_path_node,
        ):
            failures.append(f"Story {story.id}: no evidence path contains {requirement_path_node}.")

        for chunk_id in cited_authorized_chunks:
            chunk_path_node = f"Chunk:{chunk_id}"

            matching_path_exists = any(
                requirement_path_node in path and chunk_path_node in path for path in evidence_paths
            )

            if not matching_path_exists:
                failures.append(
                    f"Story {story.id}: requirement "
                    f"{requirement_id} and chunk {chunk_id} "
                    "do not appear together in an evidence path."
                )

    failures.extend(
        _claim_traceability_failures(
            story,
            allowed_requirement_ids=(allowed_requirement_ids),
            requirement_evidence_map=(requirement_evidence_map),
        )
    )

    return failures


def _local_traceability_report(
    messages: Sequence[str],
) -> QualityValidationReport:
    """Create a deterministic failed validation report."""

    return QualityValidationReport(
        status="failed",
        messages=list(messages),
        checks={
            "schema_complete": True,
            "evidence_traceable": False,
            "citations_supported": False,
            "unsupported_claims_absent": False,
            "deterministic_traceability": False,
        },
    )


def _repair_requirement_batches(
    state: UserStoryGenerationState,
    *,
    batch_size: int,
) -> list[tuple[RequirementRecord, ...]]:
    """Return only batches affected by failed stories or coverage."""

    story_driving_requirements = [
        requirement
        for requirement in state.get(
            "ledger_requirements",
            [],
        )
        if (requirement.story_driving or requirement.coverage_required)
    ]

    all_batches = list(
        _batched(
            story_driving_requirements,
            batch_size,
        )
    )

    repair_story_ids = set(state.get("repair_story_ids", []))
    repair_requirement_ids = set(state.get("repair_requirement_ids", []))

    story_batch_requirement_ids = state.get(
        "story_batch_requirement_ids",
        {},
    )

    for story_id in repair_story_ids:
        repair_requirement_ids.update(
            story_batch_requirement_ids.get(
                story_id,
                [],
            )
        )

    affected_batches: list[tuple[RequirementRecord, ...]] = []

    for requirement_batch in all_batches:
        batch_requirement_ids = {
            (requirement.canonical_id or requirement.requirement_id)
            for requirement in requirement_batch
        }

        if batch_requirement_ids & repair_requirement_ids:
            affected_batches.append(requirement_batch)

    return affected_batches


def _generic_story_failures(story: GeneratedUserStory) -> list[str]:
    text_fields = [
        story.title,
        story.user_story,
        story.business_value,
        story.description,
        *story.acceptance_criteria,
        *story.definition_of_ready,
        *story.definition_of_done,
    ]
    haystack = "\n".join(text_fields).lower()
    failures = [
        f"Story {story.id} contains prohibited generic language: {pattern}"
        for pattern in _GENERIC_STORY_PATTERNS
        if pattern in haystack
    ]
    if story.user_story.lower().startswith("as an operator, i want the system to satisfy"):
        failures.append(f"Story {story.id} uses a generic operator fallback template.")
    return failures


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
    try:
        return await method(
            prompt=prompt,
            schema=schema,
            generation_config=generation_config,
        )
    except Exception as exc:
        if hasattr(fallback, "model_copy") and hasattr(fallback, "rationale"):
            return fallback.model_copy(
                update={
                    "rationale": (
                        f"{fallback.rationale} Structured provider fallback after "
                        f"{type(exc).__name__}: {str(exc)[:240]}"
                    )
                }
            )
        return fallback


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
    requirements: list[RequirementRecord] | None = None,
) -> RetrievalPlan:
    default = _default_retrieval_plan(request)
    target_ids = [
        requirement.canonical_id or requirement.requirement_id
        for requirement in requirements or []
        if requirement.story_driving or requirement.coverage_required
    ]
    return plan.model_copy(
        update={
            "lexical_queries": plan.lexical_queries or default.lexical_queries,
            "semantic_queries": plan.semantic_queries or default.semantic_queries,
            "graph_entities": plan.graph_entities or default.graph_entities,
            "graph_relationships": plan.graph_relationships or default.graph_relationships,
            "target_requirement_ids": plan.target_requirement_ids or target_ids,
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


def _story_requirement_ids_by_story(
    stories: list[Any],
) -> dict[str, list[str]]:
    by_story: dict[str, list[str]] = {}
    for story in stories:
        story_id = str(getattr(story, "id", "") or "")
        payload = story.model_dump(mode="json") if hasattr(story, "model_dump") else {}
        ids: list[str] = []
        direct = payload.get("covered_requirement_ids")
        if isinstance(direct, list):
            ids.extend(str(item) for item in direct if item)
        traceability = payload.get("traceability")
        if isinstance(traceability, dict):
            for key in ("requirement_ids", "covered_requirement_ids", "requirements"):
                value = traceability.get(key)
                if isinstance(value, list):
                    ids.extend(str(item) for item in value if item)
                elif isinstance(value, str) and value:
                    ids.append(value)
        by_story[story_id] = sorted(set(ids))
    return by_story


def _coverage_summary_message(state: UserStoryGenerationState) -> str:
    requirements = state.get("ledger_requirements", [])
    matrix = state.get("coverage_payload", {})
    rows = cast(list[dict[str, Any]], matrix.get("rows", [])) if isinstance(matrix, dict) else []
    story_driving = [
        requirement
        for requirement in requirements
        if requirement.story_driving or requirement.coverage_required
    ]
    covered = [row for row in rows if row.get("coverage_status") == "covered"]
    deferred = [row for row in rows if row.get("coverage_status") == "deferred"]
    missing = [row for row in rows if row.get("coverage_status") == "missing"]
    denominator = len([row for row in rows if row.get("coverage_required")])
    percentage = (len(covered) / denominator * 100.0) if denominator else 100.0
    return (
        "Coverage summary: "
        f"total ledger records={len(requirements)}, "
        f"story-driving requirements={len(story_driving)}, "
        f"covered={len(covered)}, deferred={len(deferred)}, missing={len(missing)}, "
        f"coverage={percentage:.1f}%"
    )


def _append_debug_record(
    state: UserStoryGenerationState,
    *,
    filename: str,
    collection_key: str,
    record: dict[str, Any],
) -> Path | None:
    """Append one redacted record to a run-scoped debug artifact."""

    run_dir = state.get("run_dir")

    if run_dir is None:
        return None

    path = run_dir / "debug" / filename
    records: list[dict[str, Any]] = []

    if path.exists():
        try:
            existing_payload = json.loads(path.read_text(encoding="utf-8"))

            if isinstance(existing_payload, dict):
                existing_records = existing_payload.get(
                    collection_key,
                    [],
                )

                if isinstance(existing_records, list):
                    records = [item for item in existing_records if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            records = []

    redacted_record = redact_secrets(record)

    if not isinstance(redacted_record, dict):
        redacted_record = {
            "value": redacted_record,
        }

    records.append(
        cast(
            dict[str, Any],
            redacted_record,
        )
    )

    write_json_artifact(
        path,
        {
            collection_key: records,
        },
    )

    return path


def _reasoning_response_metadata(
    reasoning_client: Any,
) -> dict[str, Any]:
    """Return provider response metadata when the client exposes it."""

    metadata = getattr(
        reasoning_client,
        "_last_response_metadata",
        None,
    )

    if not isinstance(metadata, dict):
        metadata = getattr(
            reasoning_client,
            "last_response_metadata",
            None,
        )

    if not isinstance(metadata, dict):
        return {}

    redacted = redact_secrets(dict(metadata))

    return cast(dict[str, Any], redacted) if isinstance(redacted, dict) else {}


def _write_generation_attempt(
    state: UserStoryGenerationState,
    *,
    phase: Literal["generation", "repair"],
    status: Literal["succeeded", "failed"],
    batch_index: int,
    batch_count: int,
    requirement_ids: Sequence[str],
    source_chunk_ids: Sequence[str],
    stories: Sequence[GeneratedUserStory] = (),
    provider_metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> Path | None:
    """Persist one generation or repair attempt."""

    return _append_debug_record(
        state,
        filename="generation_attempts.json",
        collection_key="attempts",
        record={
            "run_id": state.get("run_id"),
            "captured_at": datetime.now(UTC).isoformat(),
            "phase": phase,
            "status": status,
            "retry_count": state.get(
                "retry_count",
                0,
            ),
            "batch_index": batch_index,
            "batch_count": batch_count,
            "requirement_ids": list(requirement_ids),
            "source_chunk_ids": list(source_chunk_ids),
            "story_count": len(stories),
            "stories": [story.model_dump(mode="json") for story in stories],
            "provider_metadata": (provider_metadata or {}),
            "error": error,
        },
    )


def _write_validation_attempt(
    state: UserStoryGenerationState,
    *,
    outcome: Literal[
        "passed",
        "repair",
        "failed",
    ],
    reports_by_story: dict[
        str,
        QualityValidationReport,
    ],
    story_failures: dict[str, list[str]],
    coverage: dict[str, object] | None = None,
    error: str | None = None,
) -> Path | None:
    """Persist one deterministic/provider validation pass."""

    return _append_debug_record(
        state,
        filename="validation_attempts.json",
        collection_key="attempts",
        record={
            "run_id": state.get("run_id"),
            "captured_at": datetime.now(UTC).isoformat(),
            "outcome": outcome,
            "retry_count": state.get(
                "retry_count",
                0,
            ),
            "pending_validation_story_ids": (
                state.get(
                    "pending_validation_story_ids",
                    [],
                )
            ),
            "reports_by_story": {
                story_id: report.model_dump(mode="json")
                for story_id, report in (reports_by_story.items())
            },
            "story_failures": story_failures,
            "coverage": coverage or {},
            "error": error,
        },
    )


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


def _generation_error_from_exception(exc: Exception) -> UserStoryGenerationError:
    message = str(exc)
    lowered = message.lower()
    if any(
        marker in lowered
        for marker in (
            "finish_reason=length",
            "finish_reason = length",
            '"finish_reason": "length"',
            "truncated",
            "token limit",
            "max_output_tokens",
            "maximum output",
            "context length",
        )
    ):
        return GenerationTokenLimitError(
            f"Structured user-story generation was truncated or exceeded token limits: "
            f"{type(exc).__name__}: {message}"
        )
    return StructuredGenerationError(
        "Structured user-story generation failed and no fallback story generation is "
        f"allowed: {type(exc).__name__}: {message}"
    )


def _write_provider_error(
    state: UserStoryGenerationState,
    typed_error: UserStoryGenerationError,
    *,
    original_exc: Exception,
    stage: str,
    provider: str,
    deployment: str,
    prompt_version: str,
    task_name: str,
    requested_max_output_tokens: int,
    invalid_model_output_path: Path | None = None,
) -> Path:
    run_dir = state.get("run_dir")
    if run_dir is None:
        raise typed_error
    path = run_dir / "debug" / "provider_errors.json"
    existing_errors: list[dict[str, Any]] = []
    if path.exists():
        try:
            existing_payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing_payload, dict) and isinstance(
                existing_payload.get("errors"),
                list,
            ):
                existing_errors = [
                    item for item in existing_payload["errors"] if isinstance(item, dict)
                ]
        except json.JSONDecodeError:
            existing_errors = []
    request = state.get("request")
    existing_errors.append(
        cast(
            dict[str, Any],
            redact_secrets(
                {
                    "run_id": state.get("run_id"),
                    "stage": stage,
                    "task_name": task_name,
                    "error_type": type(typed_error).__name__,
                    "error": str(typed_error),
                    "original_error_type": type(original_exc).__name__,
                    "original_error": str(original_exc),
                    "provider": provider,
                    "deployment": deployment,
                    "prompt_version": prompt_version,
                    "request_id": getattr(original_exc, "request_id", None),
                    "finish_reason": getattr(original_exc, "finish_reason", None),
                    "token_usage": getattr(original_exc, "usage", None),
                    "retry_count": state.get("retry_count", 0),
                    "requested_max_output_tokens": requested_max_output_tokens,
                    "redacted_request_metadata": {
                        "system": request.system if request else None,
                        "kb": request.kb if request else None,
                        "version": request.version if request else None,
                    },
                    "invalid_model_output_path": str(invalid_model_output_path)
                    if invalid_model_output_path
                    else None,
                    "captured_at": datetime.now(UTC).isoformat(),
                }
            ),
        )
    )
    write_json_artifact(path, {"errors": existing_errors})
    return path


def _write_story_quality_artifacts(
    artifact_dir: Path,
    stories: list[GeneratedUserStory],
    reports: list[QualityValidationReport],
    coverage: dict[str, object],
) -> list[Path]:
    report_entries: list[dict[str, Any]] = [
        {
            "story_id": story.id,
            "validation": report.model_dump(mode="json"),
        }
        for story, report in zip(stories, reports, strict=False)
    ]
    report_payload = {
        "schema_version": "story-quality-report-v1",
        "story_count": len(stories),
        "reports": report_entries,
        "coverage": coverage,
    }
    json_path = artifact_dir / "story_quality_report.json"
    md_path = artifact_dir / "story_quality_report.md"
    write_json_artifact(json_path, report_payload)
    md_lines = [
        "# Story Quality Report",
        "",
        f"- Story count: {len(stories)}",
        f"- Validation reports: {len(reports)}",
    ]
    counts = coverage.get("counts") if isinstance(coverage, dict) else None
    if isinstance(counts, dict):
        md_lines.append(f"- Coverage counts: {json.dumps(counts, sort_keys=True)}")
    for item in report_entries:
        validation = item["validation"]
        md_lines.append(
            f"- {item['story_id']}: {validation.get('status')} "
            f"({'; '.join(validation.get('messages', [])) or 'no messages'})"
        )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return [json_path, md_path]


def _write_run_manifest(
    state: UserStoryGenerationState,
    result: UserStoryGenerationResult,
) -> Path | None:
    run_dir = state.get("run_dir")
    if run_dir is None:
        return None
    manifest_path = run_dir / "run_manifest.json"
    request = state.get("request")
    payload = {
        "run_id": state.get("run_id"),
        "run_status": result.status,
        "publication_status": "failed" if result.status == "failed" else "published",
        "scope": {
            "system": request.system if request else None,
            "kb": request.kb if request else None,
            "version": request.version if request else None,
        },
        "requirement_counts": (
            state.get("coverage_payload", {}).get("counts")
            if isinstance(state.get("coverage_payload"), dict)
            else {}
        ),
        "story_groups": state.get("story_group_plan", []),
        "generation_attempts": {
            "retry_count": state.get("retry_count", 0),
            "failure_error_type": state.get("failure_error_type"),
            "failure_stage": state.get("failure_stage"),
        },
        "validation_results": [
            report.model_dump(mode="json") for report in state.get("validation_reports", [])
        ],
        "validation_failures": state.get(
            "validation_failures",
            [],
        ),
        "story_validation_failures": state.get(
            "story_validation_failures",
            {},
        ),
        "coverage_results": state.get(
            "coverage_payload",
            {},
        ),
        "published_artifacts": [str(path) for path in state.get("artifact_paths", [])],
        "errors": state.get("errors", []),
        "warnings": [],
        "redacted_provider_configuration": {
            "provider": _settings_value(state, "reasoning_provider"),
            "model": _settings_value(state, "reasoning_model"),
        },
        "debug_artifacts": {
            "framework_log": str(state.get("framework_log_path"))
            if state.get("framework_log_path")
            else None,
            "generation_attempts": str(state.get("generation_attempts_path"))
            if state.get("generation_attempts_path")
            else None,
            "validation_attempts": str(state.get("validation_attempts_path"))
            if state.get("validation_attempts_path")
            else None,
            "retrieval_trace": str(state.get("debug_trace_path"))
            if state.get("debug_trace_path")
            else None,
            "generation_trace": str(state.get("generation_trace_path"))
            if state.get("generation_trace_path")
            else None,
            "validation_trace": str(state.get("validation_trace_path"))
            if state.get("validation_trace_path")
            else None,
            "provider_errors": str(state.get("provider_errors_path"))
            if state.get("provider_errors_path")
            else None,
        },
        "created_at": datetime.now(UTC).isoformat(),
    }
    write_json_artifact(manifest_path, redact_secrets(payload))
    return manifest_path


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
        "ledger_requirement_count": len(state.get("ledger_requirements", [])),
        "ledger_requirement_ids": [
            requirement.canonical_id or requirement.requirement_id
            for requirement in state.get("ledger_requirements", [])
        ],
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
        "coverage": state.get("coverage_payload", {}),
        "errors": state.get("errors", []),
    }


def _settings_value(state: UserStoryGenerationState, name: str) -> str | None:
    metadata = state.get("trace_metadata", {})
    if isinstance(metadata, dict):
        value = metadata.get(name)
        return str(value) if value not in {None, ""} else None
    return None
