"""Public ingestion agent backed by a compiled LangGraph workflow."""

from __future__ import annotations

from multi_agentic_rag.agents.ingestion.graph import build_ingestion_graph
from multi_agentic_rag.agents.ingestion.schemas import IngestionRequest, IngestionResult
from multi_agentic_rag.agents.knowledge_base import KnowledgeBaseStoringAgent
from multi_agentic_rag.exceptions import IngestionError


class KnowledgeBaseIngestionAgent:
    """High-level GraphRAG knowledge-base ingestion agent."""

    def __init__(self, legacy_agent: KnowledgeBaseStoringAgent | None = None) -> None:
        self.legacy_agent = legacy_agent or KnowledgeBaseStoringAgent()
        self.graph = build_ingestion_graph(self.legacy_agent)

    async def run(self, request: IngestionRequest) -> IngestionResult:
        """Execute one ingestion request through the compiled StateGraph."""

        state = await self.graph.ainvoke({"request": request})
        result = IngestionResult.model_validate(state.get("result"))
        if result.status == "failed":
            raise IngestionError("; ".join(result.errors) if result.errors else "Ingestion failed.")
        return result
