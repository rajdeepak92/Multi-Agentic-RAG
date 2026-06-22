"""LangGraph-backed knowledge-base ingestion agent."""

from multi_agentic_rag.agents.ingestion.agent import KnowledgeBaseIngestionAgent
from multi_agentic_rag.agents.ingestion.graph import build_ingestion_graph
from multi_agentic_rag.agents.ingestion.schemas import IngestionRequest, IngestionResult

__all__ = [
    "IngestionRequest",
    "IngestionResult",
    "KnowledgeBaseIngestionAgent",
    "build_ingestion_graph",
]
