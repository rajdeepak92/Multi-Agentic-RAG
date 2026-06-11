"""Deterministic Neo4j GraphRAG retrieval helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore


@dataclass(frozen=True)
class GraphRetrievalResult:
    """Graph query records plus an optional non-fatal warning."""

    records: list[dict[str, Any]]
    warning: str | None = None


class GraphRetriever:
    """Neo4j-backed retrieval using only deterministic Cypher templates."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        graph_store: Neo4jGraphStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.graph_store = graph_store or Neo4jGraphStore(self.settings)

    def get_current_facts(self, system_name: str) -> GraphRetrievalResult:
        """Return active facts for a system."""

        return self._run(
            """
            MATCH (:System {system_name: $system_name})-[:HAS_DOCUMENT]->(d:Document {status: 'active'})
            MATCH (d)-[:HAS_CHUNK]->(c:Chunk)-[:SUPPORTS_FACT]->(f:Fact {status: 'active'})
            RETURN
                d.document_id AS document_id,
                d.source_name AS source_name,
                d.version AS version,
                d.status AS status,
                c.chunk_id AS chunk_id,
                c.page AS page,
                f.fact_id AS fact_id,
                f.fact_key AS fact_key,
                f.fact_type AS fact_type,
                f.value AS value,
                f.unit AS unit,
                f.status AS fact_status
            ORDER BY f.fact_key, f.fact_id
            """,
            system_name=system_name,
        )

    def get_historical_facts(self, system_name: str) -> GraphRetrievalResult:
        """Return superseded facts for a system."""

        return self._run(
            """
            MATCH (:System {system_name: $system_name})-[:HAS_DOCUMENT]->(d:Document {status: 'superseded'})
            MATCH (d)-[:HAS_CHUNK]->(c:Chunk)-[:SUPPORTS_FACT]->(f:Fact {status: 'superseded'})
            RETURN
                d.document_id AS document_id,
                d.source_name AS source_name,
                d.version AS version,
                d.status AS status,
                c.chunk_id AS chunk_id,
                c.page AS page,
                f.fact_id AS fact_id,
                f.fact_key AS fact_key,
                f.fact_type AS fact_type,
                f.value AS value,
                f.unit AS unit,
                f.status AS fact_status
            ORDER BY d.version, f.fact_key, f.fact_id
            """,
            system_name=system_name,
        )

    def get_deltas(self, system_name: str) -> GraphRetrievalResult:
        """Return deterministic delta records for a system."""

        return self._run(
            """
            MATCH (delta:Delta {system_name: $system_name})
            RETURN
                delta.delta_id AS delta_id,
                delta.fact_key AS fact_key,
                delta.from_version AS from_version,
                delta.to_version AS to_version,
                delta.change_type AS change_type,
                delta.old_value AS old_value,
                delta.new_value AS new_value,
                delta.risk_level AS risk_level
            ORDER BY delta.from_version, delta.to_version, delta.fact_key
            """,
            system_name=system_name,
        )

    def get_lineage(self, system_name: str) -> GraphRetrievalResult:
        """Return document lineage for a system."""

        return self._run(
            """
            MATCH (:System {system_name: $system_name})-[:HAS_DOCUMENT]->(d:Document)
            OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Document)
            OPTIONAL MATCH (newer:Document)-[:SUPERSEDES]->(d)
            RETURN
                d.document_id AS document_id,
                d.version AS version,
                d.status AS status,
                d.source_name AS source_name,
                old.document_id AS supersedes,
                newer.document_id AS superseded_by
            ORDER BY d.version, d.document_id
            """,
            system_name=system_name,
        )

    def get_related_subgraph(
        self,
        *,
        system_name: str,
        entity_text: str,
        max_records: int = 50,
    ) -> GraphRetrievalResult:
        """Return a bounded active subgraph around a named entity or fact key."""

        return self._run(
            """
            MATCH (:System {system_name: $system_name})-[:HAS_DOCUMENT]->(d:Document {status: 'active'})
            MATCH (d)-[:HAS_CHUNK]->(c:Chunk)
            MATCH path = (c)-[*1..2]-(n)
            WHERE toLower(coalesce(n.name, n.fact_key, n.requirement_id, n.value, ''))
                CONTAINS toLower($entity_text)
            RETURN
                d.document_id AS document_id,
                d.version AS version,
                c.chunk_id AS chunk_id,
                labels(n) AS labels,
                properties(n) AS properties,
                length(path) AS hops
            ORDER BY hops ASC
            LIMIT $max_records
            """,
            system_name=system_name,
            entity_text=entity_text,
            max_records=max_records,
        )

    def retrieve(self, query: str, *, system_name: str) -> list[dict[str, Any]]:
        """Backward-compatible current-fact retrieval facade."""

        _ = query
        return self.get_current_facts(system_name).records

    def _run(self, cypher: str, **params: Any) -> GraphRetrievalResult:
        available, message = self.graph_store.check_connection()
        if not available:
            return GraphRetrievalResult(records=[], warning=message)
        try:
            with self.graph_store.session() as session:
                result = session.run(cypher, params)
                return GraphRetrievalResult(records=[dict(record) for record in result])
        except Exception as exc:  # pragma: no cover - depends on local Neo4j
            return GraphRetrievalResult(records=[], warning=str(exc))
        finally:
            self.graph_store.close()
