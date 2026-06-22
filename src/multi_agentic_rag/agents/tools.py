"""Reusable tool registry for high-level agents."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    """Application-owned operation exposed to workflow agents."""

    name: str
    description: str
    side_effecting: bool = False
    handler: Callable[..., Any] | None = None


class ToolRegistry:
    """Registry of shared concrete operations and their tool descriptions."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        """Register one tool definition."""

        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        """Return one registered tool definition."""

        return self._tools[name]

    def names(self) -> list[str]:
        """Return tool names in deterministic order."""

        return sorted(self._tools)

    def descriptions(self) -> list[dict[str, Any]]:
        """Return OpenAI-friendly tool descriptions."""

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "side_effecting": tool.side_effecting,
            }
            for tool in (self._tools[name] for name in self.names())
        ]


def build_default_tool_registry() -> ToolRegistry:
    """Build the shared tool registry used by orchestration agents."""

    registry = ToolRegistry()
    for definition in (
        ToolDefinition("file.resolve", "Resolve and validate a local source file path."),
        ToolDefinition("file.read", "Read source document bytes or extracted text."),
        ToolDefinition("document.parse", "Parse PDF, DOCX, TXT, or Markdown into page text."),
        ToolDefinition("document.chunk", "Chunk parsed page text with deterministic overlap."),
        ToolDefinition("facts.extract", "Extract deterministic requirement and domain facts."),
        ToolDefinition(
            "version.validate",
            "Validate document version hints and predecessor availability.",
        ),
        ToolDefinition(
            "delta.analyze",
            "Compare old and new facts for added, removed, modified, and unchanged deltas.",
        ),
        ToolDefinition(
            "postgres.persist",
            "Persist systems, documents, versions, chunks, facts, deltas, and audits.",
            side_effecting=True,
        ),
        ToolDefinition(
            "chroma.index",
            "Embed and upsert chunks into the mandatory Chroma vector index.",
            side_effecting=True,
        ),
        ToolDefinition(
            "neo4j.project",
            "Project versioned GraphRAG nodes and generated artifact lineage.",
            side_effecting=True,
        ),
        ToolDefinition(
            "retrieval.hybrid",
            "Run BM25, vector, graph, RRF fusion, reranking, and evidence validation.",
        ),
        ToolDefinition(
            "evidence.validate",
            "Drop untraceable or empty retrieval results before model generation.",
        ),
        ToolDefinition(
            "artifact.write",
            "Write generated YAML and JSON debug artifacts under the configured output dir.",
            side_effecting=True,
        ),
        ToolDefinition("schema.validate", "Validate generated outputs against Pydantic schemas."),
    ):
        registry.register(definition)
    return registry
