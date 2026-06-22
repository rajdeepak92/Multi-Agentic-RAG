"""Ingestion agent public layer."""

from multi_agentic_rag.agents.high_level import AgentIngestDocument
from multi_agentic_rag.agents.knowledge_base import KnowledgeBaseStoringAgent

__all__ = ["AgentIngestDocument", "KnowledgeBaseStoringAgent"]
