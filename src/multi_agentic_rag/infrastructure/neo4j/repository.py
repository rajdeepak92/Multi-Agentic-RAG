# mypy: ignore-errors
"""Neo4j GraphRAG projection adapter."""

from __future__ import annotations

from contextlib import suppress
from importlib import import_module
from typing import Any

from multi_agentic_rag.config import Settings
from multi_agentic_rag.domain import (
    ChunkRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    DocumentVersionRecord,
    FactRecord,
)
from multi_agentic_rag.utils.hashing import stable_id

CONSTRAINTS = [
    "CREATE CONSTRAINT system_name IF NOT EXISTS FOR (n:System) REQUIRE n.system_name IS UNIQUE",
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.document_id IS UNIQUE",
    (
        "CREATE CONSTRAINT document_version_id IF NOT EXISTS "
        "FOR (n:DocumentVersion) REQUIRE n.document_version_id IS UNIQUE"
    ),
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.chunk_id IS UNIQUE",
    "CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (n:Fact) REQUIRE n.fact_id IS UNIQUE",
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.entity_id IS UNIQUE",
    "CREATE CONSTRAINT delta_id IF NOT EXISTS FOR (n:Delta) REQUIRE n.delta_id IS UNIQUE",
]
ENTITY_LABELS = {
    "sensor": "Sensor",
    "device": "Device",
    "protocol": "Protocol",
    "topic": "Topic",
}
FACT_ENTITY_RELATIONSHIPS = {
    "threshold": "THRESHOLD_FOR",
    "protocol": "IMPLEMENTS_PROTOCOL",
    "protocol_detail": "DETAILS_PROTOCOL",
    "topic": "USES_TOPIC",
}


class Neo4jGraphRepository:
    """Neo4j adapter using idempotent MERGE queries."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the Neo4j adapter.

        Args:
            settings: Runtime configuration containing Neo4j URI, credentials,
                database name, and required/fallback behavior.
        """

        self.settings = settings
        self._driver: Any | None = None

    @property
    def configured(self) -> bool:
        """Return whether enough Neo4j settings exist to attempt a connection."""

        return bool(self.settings.neo4j_uri)

    def check_connection(self) -> tuple[bool, str]:
        """Verify Neo4j connectivity."""

        if not self.configured:
            return False, "NEO4J_URI is not configured."
        try:
            self._get_driver().verify_connectivity()
        except Exception as exc:
            return False, str(exc)
        return True, "Neo4j connection verified."

    def create_constraints(self) -> None:
        """Create GraphRAG constraints."""

        with self.session() as session:
            for query in CONSTRAINTS:
                session.run(query)

    def clear(
        self,
        *,
        system_name: str | None = None,
        kb_name: str | None = None,
    ) -> int:
        """Delete graph nodes from Neo4j.

        Args:
            system_name: Optional system scope. When omitted, all graph nodes
                are deleted.
            kb_name: Optional knowledge-base scope within the selected system.

        Returns:
            Number of Neo4j nodes deleted.
        """

        cypher = """
        MATCH (n)
        WHERE ($system_name IS NULL OR n.system_name = $system_name)
          AND ($kb_name IS NULL OR n.kb_name = $kb_name)
        WITH collect(n) AS nodes, count(n) AS deleted_count
        FOREACH (node IN nodes | DETACH DELETE node)
        RETURN deleted_count
        """
        with self.session() as session:
            record = session.run(
                cypher,
                {"system_name": system_name, "kb_name": kb_name},
            ).single()
        return int(record["deleted_count"] if record else 0)

    def upsert_graph(
        self,
        *,
        document: DocumentRecord,
        document_version: DocumentVersionRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
    ) -> None:
        """Project the ingestion bundle into Neo4j.

        Args:
            document: Stable document lineage record.
            document_version: Version record for the newly ingested source.
            chunks: Chunk nodes to connect to the document version.
            facts: Fact, requirement, and entity evidence extracted from chunks.
            deltas: Change records between the previous active version and the
                ingested version.
        """

        self.create_constraints()
        with self.session() as session:
            for query, params in self.build_ingestion_cypher(
                document=document,
                document_version=document_version,
                chunks=chunks,
                facts=facts,
                deltas=deltas,
            ):
                session.run(query, params)

    def related_chunk_ids(
        self,
        *,
        query_text: str,
        system_name: str,
        kb_name: str,
        version: str | None,
        active_only: bool | None = None,
        top_k: int,
    ) -> list[str]:
        """Return chunk IDs related to matching facts or requirements.

        Args:
            query_text: Query text matched against projected fact keys and
                values.
            system_name: System filter for graph traversal.
            kb_name: Knowledge-base filter for graph traversal.
            version: Optional version filter. When omitted, any projected
                version for the system and knowledge base can match.
            active_only: Whether to restrict traversal to active evidence. When
                omitted, active evidence is used unless a specific version is
                requested.
            top_k: Maximum number of distinct chunk IDs to return.

        Returns:
            Chunk identifiers ordered by Neo4j's matching order.
        """

        if active_only is None:
            active_only = version is None
        where_version = "AND f.version = $version AND c.version = $version" if version else ""
        where_status = (
            "AND f.status = $active_status AND c.status = $active_status"
            if active_only
            else ""
        )
        cypher = f"""
        MATCH (c:Chunk)-[:SUPPORTS_FACT]->(f:Fact)
        WHERE f.system_name = $system_name
          AND f.kb_name = $kb_name
          {where_version}
          {where_status}
          AND toLower(f.fact_key + ' ' + f.value) CONTAINS toLower($query_text)
        RETURN DISTINCT c.chunk_id AS chunk_id
        LIMIT $top_k
        """
        with self.session() as session:
            records = session.run(
                cypher,
                {
                    "query_text": query_text,
                    "system_name": system_name,
                    "kb_name": kb_name,
                    "version": version,
                    "active_status": DocumentStatus.ACTIVE.value,
                    "top_k": top_k,
                },
            )
            return [str(record["chunk_id"]) for record in records]

    def run_graph_check(self) -> tuple[bool, str]:
        """Safely verify read/write/delete behavior."""

        available, message = self.check_connection()
        if not available:
            return False, message
        test_system = "__multi_agentic_rag_graph_check__"
        try:
            self.create_constraints()
            with self.session() as session:
                session.run(
                    "MERGE (s:System {system_name: $system_name})",
                    {"system_name": test_system},
                )
                record = session.run(
                    "MATCH (s:System {system_name: $system_name}) RETURN count(s) AS count",
                    {"system_name": test_system},
                ).single()
                session.run(
                    "MATCH (s:System {system_name: $system_name}) DETACH DELETE s",
                    {"system_name": test_system},
                )
            if int(record["count"] if record else 0) != 1:
                return False, "Temporary graph-check node was not readable."
        except Exception as exc:
            return False, str(exc)
        return True, "Neo4j graph-check PASS."

    def build_ingestion_cypher(
        self,
        *,
        document: DocumentRecord,
        document_version: DocumentVersionRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
    ) -> list[tuple[str, dict[str, Any]]]:
        """Build idempotent Cypher statements for tests and execution.

        Args:
            document: Stable document lineage record.
            document_version: Version record to attach to the document.
            chunks: Chunk nodes to merge and link to the version.
            facts: Fact nodes and derived requirement/entity relationships.
            deltas: Delta nodes and version relationships.

        Returns:
            Ordered Cypher statement and parameter pairs. The order preserves
            dependencies between document, chunk, fact, and delta nodes.
        """

        statements: list[tuple[str, dict[str, Any]]] = [
            (
                """
                MERGE (s:System {system_name: $system_name})
                SET s.kb_name = $kb_name
                MERGE (d:Document {document_id: $document_id})
                SET d.system_name = $system_name,
                    d.kb_name = $kb_name,
                    d.source_name = $source_name,
                    d.document_type = $document_type
                MERGE (s)-[:HAS_DOCUMENT]->(d)
                MERGE (v:DocumentVersion {document_version_id: $document_version_id})
                SET v.document_id = $document_id,
                    v.system_name = $system_name,
                    v.kb_name = $kb_name,
                    v.version = $version,
                    v.status = $status,
                    v.content_hash = $content_hash,
                    v.source_path = $source_path,
                    v.supersedes_version_id = $supersedes_version_id,
                    v.superseded_by_version_id = $superseded_by_version_id
                MERGE (d)-[:HAS_VERSION]->(v)
                """,
                {
                    **document.model_dump(mode="json"),
                    **document_version.model_dump(mode="json"),
                    "status": document_version.status.value,
                },
            )
        ]
        if document_version.supersedes_version_id:
            statements.append(
                (
                    """
                    MATCH (new:DocumentVersion {document_version_id: $new_version_id})
                    MATCH (old:DocumentVersion {document_version_id: $old_version_id})
                    SET old.status = $superseded_status,
                        old.superseded_by_version_id = $new_version_id
                    MERGE (new)-[:SUPERSEDES]->(old)
                    """,
                    {
                        "new_version_id": document_version.document_version_id,
                        "old_version_id": document_version.supersedes_version_id,
                        "superseded_status": DocumentStatus.SUPERSEDED.value,
                    },
                )
            )
            statements.append(
                (
                    """
                    MATCH (old:DocumentVersion {document_version_id: $old_version_id})
                    MATCH (old)-[:HAS_CHUNK]->(c:Chunk)
                    SET c.status = $superseded_status
                    """,
                    {
                        "old_version_id": document_version.supersedes_version_id,
                        "superseded_status": DocumentStatus.SUPERSEDED.value,
                    },
                )
            )
            statements.append(
                (
                    """
                    MATCH (old:DocumentVersion {document_version_id: $old_version_id})
                    MATCH (old)-[:HAS_CHUNK]->(:Chunk)-[:SUPPORTS_FACT]->(f:Fact)
                    SET f.status = $superseded_status
                    """,
                    {
                        "old_version_id": document_version.supersedes_version_id,
                        "superseded_status": DocumentStatus.SUPERSEDED.value,
                    },
                )
            )
            statements.append(
                (
                    """
                    MATCH (r:Requirement {document_version_id: $old_version_id})
                    SET r.status = $superseded_status
                    """,
                    {
                        "old_version_id": document_version.supersedes_version_id,
                        "superseded_status": DocumentStatus.SUPERSEDED.value,
                    },
                )
            )
        for chunk in chunks:
            statements.append(
                (
                    """
                    MATCH (v:DocumentVersion {document_version_id: $document_version_id})
                    MERGE (c:Chunk {chunk_id: $chunk_id})
                    SET c.document_id = $document_id,
                        c.system_name = $system_name,
                        c.kb_name = $kb_name,
                        c.version = $version,
                        c.status = $status,
                        c.page = $page,
                        c.chunk_index = $chunk_index,
                        c.content_hash = $content_hash
                    MERGE (v)-[:HAS_CHUNK]->(c)
                    """,
                    {**chunk.model_dump(mode="json"), "status": chunk.status.value},
                )
            )
        for fact in facts:
            statements.extend(_fact_statements(fact))
        for delta in deltas:
            statements.append(
                (
                    """
                    MERGE (delta:Delta {delta_id: $delta_id})
                    SET delta.system_name = $system_name,
                        delta.kb_name = $kb_name,
                        delta.from_version = $from_version,
                        delta.to_version = $to_version,
                        delta.fact_key = $fact_key,
                        delta.change_type = $change_type,
                        delta.risk_level = $risk_level
                    WITH delta
                    MATCH (from_v:DocumentVersion {document_version_id: $from_document_version_id})
                    MATCH (to_v:DocumentVersion {document_version_id: $to_document_version_id})
                    MERGE (delta)-[:FROM_VERSION]->(from_v)
                    MERGE (delta)-[:TO_VERSION]->(to_v)
                    """,
                    delta.model_dump(mode="json"),
                )
            )
        return statements

    def session(self) -> Any:
        """Open a Neo4j session using the configured database when provided."""

        driver = self._get_driver()
        if self.settings.neo4j_database:
            return driver.session(database=self.settings.neo4j_database)
        return driver.session()

    def close(self) -> None:
        """Close the cached Neo4j driver if it has been opened."""

        if self._driver is not None:
            with suppress(Exception):
                self._driver.close()
            self._driver = None

    def _get_driver(self) -> Any:
        if self._driver is None:
            module = import_module("neo4j")
            auth = None
            if self.settings.neo4j_username or self.settings.neo4j_password:
                auth = (self.settings.neo4j_username, self.settings.neo4j_password)
            self._driver = module.GraphDatabase.driver(self.settings.neo4j_uri, auth=auth)
        return self._driver


def _fact_statements(fact: FactRecord) -> list[tuple[str, dict[str, Any]]]:
    payload = {**fact.model_dump(mode="json"), "status": fact.status.value}
    statements: list[tuple[str, dict[str, Any]]] = [
        (
            """
            MATCH (c:Chunk {chunk_id: $chunk_id})
            MERGE (f:Fact {fact_id: $fact_id})
            SET f.fact_key = $fact_key,
                f.fact_type = $fact_type,
                f.value = $value,
                f.unit = $unit,
                f.status = $status,
                f.version = $version,
                f.semantic_key = $semantic_key,
                f.system_name = $system_name,
                f.kb_name = $kb_name,
                f.document_id = $document_id,
                f.document_version_id = $document_version_id,
                f.chunk_id = $chunk_id
            MERGE (c)-[:SUPPORTS_FACT]->(f)
            """,
            payload,
        )
    ]
    linked_requirement_id = fact.value if fact.fact_type == "requirement" else fact.requirement_id
    if linked_requirement_id:
        requirement_relationship = (
            "DESCRIBES_REQUIREMENT"
            if fact.fact_type == "requirement"
            else "TRACES_TO_REQUIREMENT"
        )
        statements.append(
            (
                f"""
                MATCH (f:Fact {{fact_id: $fact_id}})
                MERGE (r:Requirement {{
                    system_name: $system_name,
                    kb_name: $kb_name,
                    requirement_id: $linked_requirement_id
                }})
                SET r.kb_name = $kb_name,
                    r.version = $version,
                    r.status = $status,
                    r.document_id = $document_id,
                    r.document_version_id = $document_version_id,
                    r.chunk_id = $chunk_id,
                    r.text = $evidence
                MERGE (f)-[:{requirement_relationship}]->(r)
                """,
                {**payload, "linked_requirement_id": linked_requirement_id},
            )
        )
    for entity in _entities_from_fact(fact):
        relationship = entity.pop("relationship")
        label = entity.pop("label")
        relationship_clause = (
            f"MERGE (f)-[:{relationship}]->(e)" if relationship else ""
        )
        statements.append(
            (
                f"""
                MATCH (c:Chunk {{chunk_id: $chunk_id}})
                MATCH (f:Fact {{fact_id: $fact_id}})
                MERGE (e:Entity:{label} {{entity_id: $entity_id}})
                SET e.entity_type = $entity_type,
                    e.name = $name,
                    e.system_name = $system_name,
                    e.kb_name = $kb_name,
                    e.version = $version,
                    e.status = $status,
                    e.document_id = $document_id,
                    e.document_version_id = $document_version_id,
                    e.chunk_id = $chunk_id
                MERGE (c)-[:MENTIONS]->(e)
                {relationship_clause}
                """,
                {**payload, **entity},
            )
        )
    return statements


def _entities_from_fact(fact: FactRecord) -> list[dict[str, str | None]]:
    entity_type: str | None = None
    name: str | None = None
    if fact.fact_type == "threshold":
        sensor = str(fact.metadata.get("sensor") or "").lower()
        if sensor:
            entity_type = "sensor"
            name = sensor
    elif fact.fact_type == "protocol_detail":
        protocol = str(fact.metadata.get("protocol") or "").strip()
        if not protocol and fact.fact_key.startswith("protocol_detail:"):
            protocol = fact.fact_key.split(":", 2)[1]
        if protocol:
            entity_type = "protocol"
            name = _normalize_protocol_name(protocol)
    elif fact.fact_type in ENTITY_LABELS:
        entity_type = fact.fact_type
        name = _normalize_protocol_name(fact.value) if entity_type == "protocol" else fact.value
    if not entity_type or not name:
        return []
    label = ENTITY_LABELS[entity_type]
    return [
        {
            "entity_id": stable_id(
                "entity",
                fact.system_name,
                fact.kb_name,
                entity_type,
                name.lower(),
            ),
            "entity_type": entity_type,
            "name": name,
            "label": label,
            "relationship": FACT_ENTITY_RELATIONSHIPS.get(fact.fact_type),
        }
    ]


def _normalize_protocol_name(value: str) -> str:
    normalized = value.strip()
    return normalized.upper() if normalized.lower() in {"mqtt", "can", "rest"} else normalized
