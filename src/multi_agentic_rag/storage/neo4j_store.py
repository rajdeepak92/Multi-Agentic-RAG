"""Neo4j local graph store implementation."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from multi_agentic_rag.config import Settings
from multi_agentic_rag.graph.indexes import INDEX_QUERIES
from multi_agentic_rag.models import ChunkRecord, DeltaRecord, DocumentRecord, FactRecord


class Neo4jGraphStore:
    """Neo4j adapter using idempotent MERGE queries."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._driver: Any | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.neo4j_uri)

    def _get_driver(self) -> Any:
        if self._driver is None:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_username, self.settings.neo4j_password),
            )
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            with suppress(Exception):
                self._driver.close()
            self._driver = None

    def check_connection(self) -> tuple[bool, str]:
        if not self.configured:
            return False, "NEO4J_URI is not configured."
        try:
            self._get_driver().verify_connectivity()
        except Exception as exc:  # pragma: no cover - depends on local Neo4j
            return False, str(exc)
        return True, "Neo4j connection verified."

    def create_indexes(self) -> None:
        driver = self._get_driver()
        with driver.session() as session:
            for query in INDEX_QUERIES:
                session.run(query)

    def run_graph_check(
        self,
        *,
        test_system_name: str = "**MULTI_AGENTIC_RAG_GRAPH_CHECK**",
    ) -> tuple[bool, str]:
        """Safely verify Neo4j read/write/delete without touching real graph data."""

        available, message = self.check_connection()
        if not available:
            return False, message
        try:
            self.create_indexes()
            driver = self._get_driver()
            with driver.session() as session:
                session.run(
                    """
                    MERGE (s:System {system_name: $system_name})
                    SET s.graph_check = true
                    """,
                    {"system_name": test_system_name},
                )
                record = session.run(
                    """
                    MATCH (s:System {system_name: $system_name})
                    RETURN count(s) AS count
                    """,
                    {"system_name": test_system_name},
                ).single()
                count = record["count"] if record else 0
                session.run(
                    """
                    MATCH (s:System {system_name: $system_name})
                    DETACH DELETE s
                    """,
                    {"system_name": test_system_name},
                )
            if count != 1:
                return False, f"Temporary graph-check node read count was {count}."
        except Exception as exc:  # pragma: no cover - depends on local Neo4j
            return False, str(exc)
        return True, "Neo4j graph-check PASS."

    def upsert_ingestion_graph(
        self,
        *,
        document: DocumentRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
    ) -> None:
        driver = self._get_driver()
        with driver.session() as session:
            session.run(
                """
                MERGE (s:System {system_name: $system_name})
                MERGE (d:Document {document_id: $document_id})
                SET d.version = $version,
                    d.status = $status,
                    d.system_name = $system_name,
                    d.source_name = $source_name,
                    d.content_hash = $content_hash
                MERGE (s)-[:HAS_DOCUMENT]->(d)
                """,
                {
                    "system_name": document.system_name,
                    "document_id": document.document_id,
                    "version": document.version,
                    "status": document.status.value,
                    "source_name": document.source_name,
                    "content_hash": document.content_hash,
                },
            )
            if document.supersedes:
                session.run(
                    """
                    MATCH (new:Document {document_id: $new_document_id})
                    MATCH (old:Document {document_id: $old_document_id})
                    MERGE (new)-[:SUPERSEDES]->(old)
                    """,
                    {
                        "new_document_id": document.document_id,
                        "old_document_id": document.supersedes,
                    },
                )
            if document.superseded_by:
                session.run(
                    """
                    MATCH (new:Document {document_id: $new_document_id})
                    MATCH (old:Document {document_id: $old_document_id})
                    MERGE (new)-[:SUPERSEDES]->(old)
                    """,
                    {
                        "new_document_id": document.superseded_by,
                        "old_document_id": document.document_id,
                    },
                )
            for chunk in chunks:
                session.run(
                    """
                    MATCH (d:Document {document_id: $document_id})
                    MERGE (c:Chunk {chunk_id: $chunk_id})
                    SET c.system_name = $system_name,
                        c.version = $version,
                        c.status = $status,
                        c.page = $page,
                        c.chunk_index = $chunk_index,
                        c.content_hash = $content_hash
                    MERGE (d)-[:HAS_CHUNK]->(c)
                    """,
                    {
                        "document_id": chunk.document_id,
                        "chunk_id": chunk.chunk_id,
                        "system_name": chunk.system_name,
                        "version": chunk.version,
                        "status": chunk.status.value,
                        "page": chunk.page,
                        "chunk_index": chunk.chunk_index,
                        "content_hash": chunk.content_hash,
                    },
                )
            for fact in facts:
                self._upsert_fact(session, fact)
            for delta in deltas:
                session.run(
                    """
                    MERGE (delta:Delta {delta_id: $delta_id})
                    SET delta.system_name = $system_name,
                        delta.from_version = $from_version,
                        delta.to_version = $to_version,
                        delta.fact_key = $fact_key,
                        delta.change_type = $change_type,
                        delta.change_magnitude = $change_magnitude,
                        delta.old_value = $old_value,
                        delta.new_value = $new_value,
                        delta.affected_requirement_id = $affected_requirement_id,
                        delta.risk_level = $risk_level
                    WITH delta
                    MATCH (from_doc:Document {version: $from_version, system_name: $system_name})
                    MATCH (to_doc:Document {version: $to_version, system_name: $system_name})
                    MERGE (delta)-[:FROM_DOCUMENT]->(from_doc)
                    MERGE (delta)-[:TO_DOCUMENT]->(to_doc)
                    """,
                    delta.model_dump(mode="json"),
                )

    @staticmethod
    def _upsert_fact(session: Any, fact: FactRecord) -> None:
        session.run(
            """
            MATCH (c:Chunk {chunk_id: $chunk_id})
            MERGE (f:Fact {fact_id: $fact_id})
            SET f.fact_key = $fact_key,
                f.fact_type = $fact_type,
                f.value = $value,
                f.unit = $unit,
                f.status = $status,
                f.version = $version,
                f.system_name = $system_name,
                f.document_id = $document_id,
                f.chunk_id = $chunk_id
            MERGE (c)-[:SUPPORTS_FACT]->(f)
            """,
            fact.model_dump(mode="json"),
        )
        if fact.fact_type == "requirement":
            session.run(
                """
                MATCH (c:Chunk {chunk_id: $chunk_id})
                MATCH (f:Fact {fact_id: $fact_id})
                MERGE (r:Requirement {requirement_id: $requirement_id})
                SET r.status = $status,
                    r.version = $version,
                    r.system_name = $system_name,
                    r.document_id = $document_id,
                    r.chunk_id = $chunk_id,
                    r.text = $evidence
                MERGE (f)-[:DESCRIBES_REQUIREMENT]->(r)
                """,
                {
                    **fact.model_dump(mode="json"),
                    "requirement_id": fact.requirement_id or fact.value,
                },
            )
        if fact.fact_type in {"sensor", "protocol"}:
            session.run(
                """
                MATCH (c:Chunk {chunk_id: $chunk_id})
                MERGE (e:Entity {entity_id: $entity_id})
                SET e.name = $name,
                    e.entity_type = $entity_type,
                    e.status = $status,
                    e.version = $version
                MERGE (c)-[:MENTIONS]->(e)
                """,
                {
                    "chunk_id": fact.chunk_id,
                    "entity_id": f"{fact.fact_type}:{fact.value.lower()}",
                    "name": fact.value,
                    "entity_type": fact.fact_type,
                    "status": fact.status.value,
                    "version": fact.version,
                },
            )
