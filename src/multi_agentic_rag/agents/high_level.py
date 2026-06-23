"""Standalone high-level agents used by LangGraph workflows and direct callers."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from multi_agentic_rag.agents.artifacts import UserStoryArtifactWriter
from multi_agentic_rag.agents.chat import EVIDENCE_NOT_FOUND_MESSAGE
from multi_agentic_rag.agents.knowledge_base import KnowledgeBaseStoringAgent
from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.domain import (
    AgentRunResult,
    AgentRunStatus,
    ArtifactManifest,
    ArtifactRecord,
    EvidenceBundle,
    GeneratedUserStory,
    GroundedAnswer,
    IngestResult,
    QualityValidationReport,
    RankedRetrievalResult,
    RequirementEvidenceRecord,
    RequirementRecord,
    RequirementType,
    RetrievalResult,
    TaskIntent,
)
from multi_agentic_rag.exceptions import MultiAgenticRagError
from multi_agentic_rag.llm import ReasoningClient
from multi_agentic_rag.requirements_ledger import (
    RequirementQueryIntent,
    classify_requirement_query,
    render_requirement_answer,
    requirement_inventory_payload,
    write_requirement_inventory_artifacts,
)
from multi_agentic_rag.retrieval.evidence import EvidenceValidator


class AgentRetriever(Protocol):
    """Retriever contract for high-level agents."""

    async def retrieve(
        self,
        query_text: str,
        *,
        system_name: str,
        kb_name: str = "default",
        version: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Retrieve candidate evidence."""


class ArtifactAuditRepository(Protocol):
    """Audit repository contract for generated artifacts."""

    async def record_artifact(self, record: ArtifactRecord) -> None:
        """Persist one artifact audit record."""


class ArtifactGraphRepository(Protocol):
    """Graph repository contract for generated artifact lineage."""

    def upsert_user_story_artifact(
        self,
        *,
        manifest: ArtifactManifest,
        story_payload: dict[str, Any],
        system_name: str,
        kb_name: str,
        version: str,
    ) -> None:
        """Project user-story artifact lineage into Neo4j."""


class RequirementLedgerRepository(Protocol):
    """Exact requirement-ledger enumeration contract."""

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


class AgentIngestDocument:
    """Standalone document-ingestion agent."""

    name = "AgentIngestDocument"

    def __init__(self, ingestion_agent: KnowledgeBaseStoringAgent | None = None) -> None:
        self.ingestion_agent = ingestion_agent or KnowledgeBaseStoringAgent()

    async def run(self, intent: TaskIntent) -> AgentRunResult:
        """Run ingestion for the first document in the intent."""

        if not intent.system:
            return _blocked("system is required for ingestion")
        if not intent.version:
            return _blocked("version is required for ingestion")
        if not intent.documents:
            return _blocked("document path is required for ingestion")
        try:
            result = await self.ingestion_agent.ingest(
                Path(intent.documents[0]),
                intent.kb,
                system=intent.system,
                version=intent.version,
            )
        except MultiAgenticRagError as exc:
            return AgentRunResult(status=AgentRunStatus.FAILED, messages=[str(exc)])
        return _ingest_success(result)


class AgentRetrieveAnswer:
    """Retrieve evidence and synthesize an OpenAI-grounded answer."""

    name = "AgentRetrieveAnswer"

    def __init__(
        self,
        retriever: AgentRetriever,
        reasoning_client: ReasoningClient,
        *,
        settings: Settings | None = None,
        requirement_repository: RequirementLedgerRepository | None = None,
        evidence_validator: EvidenceValidator | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.retriever = retriever
        self.reasoning_client = reasoning_client
        self.requirement_repository = requirement_repository
        self.evidence_validator = evidence_validator or EvidenceValidator()

    async def run(
        self,
        intent: TaskIntent,
        *,
        question: str,
        top_k: int | None = None,
    ) -> AgentRunResult:
        """Delegate answer generation to the internal ask graph."""

        from multi_agentic_rag.agents.ask import run_ask_graph

        return await run_ask_graph(self, intent, question=question, top_k=top_k)

    async def _run_direct(
        self,
        intent: TaskIntent,
        *,
        question: str,
        top_k: int | None = None,
    ) -> AgentRunResult:
        """Run hybrid retrieval and answer synthesis."""

        if not intent.system:
            return _blocked("system is required for answer generation")
        query_intent = classify_requirement_query(question)
        if (
            query_intent == RequirementQueryIntent.EXHAUSTIVE_REQUIREMENT_QUERY
            and self.requirement_repository is not None
        ):
            if not intent.version:
                return _blocked("version is required for exhaustive requirement enumeration")
            requirements = await self.requirement_repository.list_requirements_for_scope(
                system_name=intent.system,
                kb_name=intent.kb,
                version=intent.version,
                active_only=True,
            )
            requirement_evidence = await self.requirement_repository.list_requirement_evidence(
                requirement_pks=[
                    requirement.requirement_pk
                    for requirement in requirements
                    if requirement.requirement_pk
                ]
            )
            payload = requirement_inventory_payload(
                requirements,
                requirement_evidence,
                system_name=intent.system,
                kb_name=intent.kb,
                version=intent.version,
            )
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            output_dir = (
                self.settings.user_story_output_dir
                / "requirements"
                / intent.system
                / intent.kb
                / intent.version
                / timestamp
            )
            artifact_paths = write_requirement_inventory_artifacts(
                output_dir=output_dir,
                payload=payload,
            )
            answer_text = render_requirement_answer(payload, artifact_paths)
            return AgentRunResult(
                status=AgentRunStatus.SUCCEEDED,
                messages=[answer_text],
                evidence_ids=list(
                    dict.fromkeys(item.chunk_id for item in requirement_evidence)
                ),
                artifact_paths=[str(path) for path in artifact_paths],
                payload={
                    "answer": answer_text,
                    "query_intent": query_intent.value,
                    "requirements_inventory": payload,
                    "artifacts": [str(path) for path in artifact_paths],
                },
            )
        results = await self.retriever.retrieve(
            question,
            system_name=intent.system,
            kb_name=intent.kb,
            version=intent.version,
            top_k=top_k or self.settings.retrieval_answer_top_k,
        )
        evidence = self.evidence_validator.validate(results)
        if not evidence:
            return AgentRunResult(
                status=AgentRunStatus.REFUSED,
                messages=[EVIDENCE_NOT_FOUND_MESSAGE],
                payload={
                    "answer": EVIDENCE_NOT_FOUND_MESSAGE,
                    "refused": True,
                    "evidence_bundle": EvidenceBundle(
                        query=question,
                        version_scope=intent.version,
                    ).model_dump(mode="json"),
                },
            )
        bundle = _bundle(question, evidence, intent.version)
        try:
            answer = await self.reasoning_client.synthesize_answer(question, bundle)
        except MultiAgenticRagError as exc:
            return AgentRunResult(status=AgentRunStatus.FAILED, messages=[str(exc)])
        return _answer_success(answer, bundle)


class AgentUserStoryBuilder:
    """Generate YAML user stories from already-ingested evidence."""

    name = "AgentUserStoryBuilder"

    def __init__(
        self,
        retriever: AgentRetriever,
        reasoning_client: ReasoningClient,
        *,
        settings: Settings | None = None,
        writer: UserStoryArtifactWriter | None = None,
        evidence_validator: EvidenceValidator | None = None,
        artifact_audit_repository: ArtifactAuditRepository | None = None,
        graph_repository: ArtifactGraphRepository | None = None,
        generation_agent: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.retriever = retriever
        self.reasoning_client = reasoning_client
        self.writer = writer or UserStoryArtifactWriter(self.settings)
        self.evidence_validator = evidence_validator or EvidenceValidator()
        self.artifact_audit_repository = artifact_audit_repository
        self.graph_repository = graph_repository
        self.generation_agent = generation_agent

    async def run(self, intent: TaskIntent) -> AgentRunResult:
        """Generate user stories and write YAML/debug artifacts."""

        if not intent.system:
            return _blocked("system is required for user-story generation")
        if not intent.version:
            return _blocked("version is required for user-story generation")
        if self.generation_agent is not None:
            from multi_agentic_rag.agents.user_stories import UserStoryGenerationRequest

            try:
                result = await self.generation_agent.run(
                    UserStoryGenerationRequest(
                        system=intent.system,
                        kb=intent.kb,
                        version=intent.version,
                    )
                )
            except MultiAgenticRagError as exc:
                return AgentRunResult(status=AgentRunStatus.FAILED, messages=[str(exc)])
            return AgentRunResult(
                status=AgentRunStatus.SUCCEEDED,
                messages=result.messages,
                evidence_ids=result.evidence_ids,
                artifact_paths=[str(path) for path in result.artifact_paths],
                payload={
                    "artifacts": [str(path) for path in result.artifact_paths],
                    "debug_trace_path": str(result.debug_trace_path)
                    if result.debug_trace_path
                    else None,
                    "stories": [story.model_dump(mode="json") for story in result.stories],
                    "degraded_sources": [source.value for source in result.degraded_sources],
                },
            )
        query = (
            "requirements user stories acceptance criteria non functional requirements "
            f"for {intent.system} {intent.version}"
        )
        results = await self.retriever.retrieve(
            query,
            system_name=intent.system,
            kb_name=intent.kb,
            version=intent.version,
            top_k=20,
        )
        evidence = self.evidence_validator.validate(results)
        if not evidence:
            return AgentRunResult(
                status=AgentRunStatus.FAILED,
                messages=["No traceable evidence found for user-story generation."],
            )
        bundle = _bundle(query, evidence, intent.version)
        try:
            story_batch = await self.reasoning_client.write_user_stories(bundle)
        except MultiAgenticRagError as exc:
            return AgentRunResult(status=AgentRunStatus.FAILED, messages=[str(exc)])
        try:
            validations = await _validate_stories_concurrently(
                self.reasoning_client,
                story_batch.stories,
                bundle,
            )
        except MultiAgenticRagError as exc:
            return AgentRunResult(status=AgentRunStatus.FAILED, messages=[str(exc)])
        manifests: list[ArtifactManifest] = []
        validation_messages: list[str] = []
        validation_failed = False
        for story, validation in zip(story_batch.stories, validations, strict=True):
            validation_messages.extend(validation.messages)
            if validation.status == "failed":
                validation_failed = True
            manifest = self.writer.write(
                story,
                system_name=intent.system,
                kb_name=intent.kb,
                version=intent.version,
                evidence=bundle,
                model=self.reasoning_client.model,
                prompt_version=self.reasoning_client.prompt_version,
                validation_status=validation.status,
                validation_messages=validation.messages,
            )
            manifests.append(manifest)
            if self.artifact_audit_repository:
                await self.artifact_audit_repository.record_artifact(
                    ArtifactRecord(
                        artifact_id=manifest.artifact_id,
                        system_name=intent.system,
                        kb_name=intent.kb,
                        version=intent.version,
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
                    system_name=intent.system,
                    kb_name=intent.kb,
                    version=intent.version,
                )
        if not manifests:
            return AgentRunResult(
                status=AgentRunStatus.FAILED,
                messages=["OpenAI returned no user stories."],
            )
        if validation_failed:
            return AgentRunResult(
                status=AgentRunStatus.FAILED,
                messages=["User-story validation failed.", *validation_messages],
                evidence_ids=bundle.source_chunk_ids,
                artifact_paths=[manifest.generated_file_path for manifest in manifests],
                payload={
                    "evidence_bundle": bundle.model_dump(mode="json"),
                    "artifacts": [manifest.model_dump(mode="json") for manifest in manifests],
                    "validation_messages": validation_messages,
                },
            )
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            messages=["Generated user stories."],
            evidence_ids=bundle.source_chunk_ids,
            artifact_paths=[manifest.generated_file_path for manifest in manifests],
            payload={
                "evidence_bundle": bundle.model_dump(mode="json"),
                "artifacts": [manifest.model_dump(mode="json") for manifest in manifests],
                "validation_messages": validation_messages,
            },
        )


def _blocked(message: str) -> AgentRunResult:
    return AgentRunResult(status=AgentRunStatus.BLOCKED, messages=[message])


def _ingest_success(result: IngestResult) -> AgentRunResult:
    return AgentRunResult(
        status=AgentRunStatus.SUCCEEDED,
        messages=[f"Ingested document version {result.document_version_id}."],
        payload={"ingest_result": result.model_dump(mode="json")},
    )


def _answer_success(answer: GroundedAnswer, bundle: EvidenceBundle) -> AgentRunResult:
    status = AgentRunStatus.REFUSED if answer.refused else AgentRunStatus.SUCCEEDED
    return AgentRunResult(
        status=status,
        messages=[answer.answer],
        evidence_ids=bundle.source_chunk_ids,
        payload={
            "answer": answer.model_dump(mode="json"),
            "evidence_bundle": bundle.model_dump(mode="json"),
        },
    )


def _bundle(
    query: str,
    evidence: list[RankedRetrievalResult],
    version: str | None,
) -> EvidenceBundle:
    return EvidenceBundle(
        query=query,
        ranked_results=evidence,
        source_chunk_ids=[result.chunk_id for result in evidence],
        graph_paths=[result.evidence_path for result in evidence],
        version_scope=version,
    )


async def _validate_stories_concurrently(
    reasoning_client: ReasoningClient,
    stories: list[GeneratedUserStory],
    evidence: EvidenceBundle,
    *,
    concurrency: int = 3,
) -> list[QualityValidationReport]:
    semaphore = asyncio.Semaphore(concurrency)

    async def validate(story: GeneratedUserStory) -> QualityValidationReport:
        async with semaphore:
            return await reasoning_client.validate_user_story(story, evidence)

    return list(await asyncio.gather(*(validate(story) for story in stories)))
