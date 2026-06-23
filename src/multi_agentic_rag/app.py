"""Application composition root for the two GraphRAG business agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from multi_agentic_rag.agents.ingestion import (
    IngestionRequest,
    IngestionResult,
    KnowledgeBaseIngestionAgent,
)
from multi_agentic_rag.agents.knowledge_base import KnowledgeBaseStoringAgent
from multi_agentic_rag.agents.user_stories import (
    UserStoryGenerationAgent,
    UserStoryGenerationRequest,
    UserStoryGenerationResult,
    UserStoryGraphRuntime,
)
from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.infrastructure.chroma import ChromaVectorRepository
from multi_agentic_rag.infrastructure.neo4j import Neo4jGraphRepository
from multi_agentic_rag.infrastructure.postgres import PostgresKnowledgeRepository
from multi_agentic_rag.llm import ReasoningClient, ReasoningModelSelector, build_reasoning_client
from multi_agentic_rag.retrieval import (
    BM25Retriever,
    GraphRetriever,
    VectorRetriever,
    build_lexical_repository,
)
from multi_agentic_rag.retrieval.reranker import select_reranker


@dataclass
class GraphRagApplication:
    """Composed application dependencies and public business agents."""

    settings: Settings
    reasoning_client: ReasoningClient
    ingestion_agent: KnowledgeBaseIngestionAgent
    user_story_agent: UserStoryGenerationAgent

    async def ingest(self, request: IngestionRequest) -> IngestionResult:
        """Run the independent ingestion agent."""

        return await self.ingestion_agent.run(request)

    async def user_stories(
        self,
        request: UserStoryGenerationRequest,
    ) -> UserStoryGenerationResult:
        """Run the independent user-story generation agent."""

        return await self.user_story_agent.run(request)

    async def ingest_then_user_stories(
        self,
        *,
        document_path: Path,
        system: str,
        version: str,
        kb: str = "default",
    ) -> tuple[IngestionResult, UserStoryGenerationResult]:
        """Compose the two agents without introducing a third business agent."""

        ingest_result = await self.ingest(
            IngestionRequest(
                document_path=document_path,
                system=system,
                version=version,
                kb=kb,
            )
        )
        story_result = await self.user_stories(
            UserStoryGenerationRequest(system=system, version=version, kb=kb)
        )
        return ingest_result, story_result


def build_application(
    *,
    settings: Settings | None = None,
    model_selector: ReasoningModelSelector | None = None,
    reasoning_client: ReasoningClient | None = None,
    review_facts: bool = False,
) -> GraphRagApplication:
    """Construct settings, providers, repositories, retrievers, graphs, and agents."""

    loaded_settings = settings or get_settings()
    loaded_settings.ensure_project_cache_paths()
    reasoning_client = reasoning_client or build_reasoning_client(loaded_settings, model_selector)

    postgres = PostgresKnowledgeRepository.from_settings(loaded_settings)
    chroma = ChromaVectorRepository.from_settings(loaded_settings)
    graph = Neo4jGraphRepository(loaded_settings)
    lexical = build_lexical_repository(loaded_settings)

    legacy_ingestion = KnowledgeBaseStoringAgent(
        settings=loaded_settings,
        fact_review_client=reasoning_client if review_facts else None,
        review_facts=review_facts,
        postgres_agent=None,
        chroma_agent=None,
        neo4j_agent=None,
    )
    ingestion_agent = KnowledgeBaseIngestionAgent(legacy_ingestion)

    user_story_runtime = UserStoryGraphRuntime(
        settings=loaded_settings,
        reasoning_client=reasoning_client,
        postgres_retriever=BM25Retriever(lexical),
        chroma_retriever=VectorRetriever(chroma),
        neo4j_retriever=GraphRetriever(graph, postgres),
        reranker=select_reranker(loaded_settings),
        artifact_audit_repository=postgres,
        graph_repository=graph,
        requirement_repository=postgres,
    )
    return GraphRagApplication(
        settings=loaded_settings,
        reasoning_client=reasoning_client,
        ingestion_agent=ingestion_agent,
        user_story_agent=UserStoryGenerationAgent(user_story_runtime),
    )
