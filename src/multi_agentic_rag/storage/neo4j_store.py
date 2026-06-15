"""Neo4j local graph store implementation."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from multi_agentic_rag.config import Settings
from multi_agentic_rag.graph.indexes import INDEX_QUERIES
from multi_agentic_rag.models import (
    ChunkRecord,
    CoverageRecord,
    DeltaRecord,
    DocumentRecord,
    FactRecord,
    GeneratedTestFileRecord,
    TestRunResultRecord,
)


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
                auth=self._auth(),
            )
        return self._driver

    def _auth(self) -> tuple[str, str] | None:
        username = self.settings.neo4j_username.strip()
        password = self.settings.neo4j_password.strip()
        if username and password:
            return username, password
        if not username and not password:
            return None
        raise ValueError(
            "NEO4J_USERNAME and NEO4J_PASSWORD must both be set, "
            "or both left empty for an unauthenticated Neo4j instance."
        )

    def session(self) -> Any:
        driver = self._get_driver()
        if self.settings.neo4j_database:
            return driver.session(database=self.settings.neo4j_database)
        return driver.session()

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
        with self.session() as session:
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
            with self.session() as session:
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

    def delete_system(self, system_name: str) -> int:
        """Delete graph nodes owned by one MARAG system."""

        available, message = self.check_connection()
        if not available:
            raise RuntimeError(message)
        with self.session() as session:
            record = session.run(
                """
                MATCH (n)
                WHERE n.system_name = $system_name
                   OR (n:System AND n.system_name = $system_name)
                WITH collect(n) AS nodes, count(n) AS deleted
                UNWIND nodes AS node
                DETACH DELETE node
                RETURN deleted
                """,
                {"system_name": system_name},
            ).single()
        return int(record["deleted"] if record else 0)

    def upsert_ingestion_graph(
        self,
        *,
        document: DocumentRecord,
        chunks: list[ChunkRecord],
        facts: list[FactRecord],
        deltas: list[DeltaRecord],
    ) -> None:
        with self.session() as session:
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

    def upsert_generated_test_graph(
        self,
        *,
        test_file: GeneratedTestFileRecord,
        coverage_records: list[CoverageRecord],
    ) -> None:
        """Upsert generated automation assets and coverage links into Neo4j."""

        with self.session() as session:
            session.run(
                """
                MERGE (s:System {system_name: $system_name})
                MERGE (t:GeneratedTest {test_file_id: $test_file_id})
                SET t.run_id = $run_id,
                    t.version = $version,
                    t.scope_hash = $scope_hash,
                    t.file_path = $file_path,
                    t.tracking_file_path = $tracking_file_path,
                    t.robot_file_path = $robot_file_path,
                    t.coverage_report_path = $coverage_report_path,
                    t.report_file_paths = $report_file_paths,
                    t.status = $status,
                    t.coverage_ids = $coverage_ids,
                    t.created_at = $created_at,
                    t.updated_at = $updated_at
                MERGE (s)-[:HAS_GENERATED_TEST]->(t)
                """,
                test_file.model_dump(mode="json"),
            )
            for coverage in coverage_records:
                self._upsert_coverage_link(session, test_file=test_file, coverage=coverage)

    def upsert_test_run_graph(
        self,
        *,
        result: TestRunResultRecord,
        test_file: GeneratedTestFileRecord | None = None,
    ) -> None:
        """Upsert generated test execution status and link it to the test asset."""

        with self.session() as session:
            if test_file:
                session.run(
                    """
                    MERGE (s:System {system_name: $system_name})
                    MERGE (t:GeneratedTest {test_file_id: $test_file_id})
                    SET t.run_id = $run_id,
                        t.version = $version,
                        t.scope_hash = $scope_hash,
                        t.file_path = $file_path,
                        t.tracking_file_path = $tracking_file_path,
                        t.robot_file_path = $robot_file_path,
                        t.coverage_report_path = $coverage_report_path,
                        t.report_file_paths = $report_file_paths,
                        t.status = $status,
                        t.coverage_ids = $coverage_ids,
                        t.created_at = $created_at,
                        t.updated_at = $updated_at
                    MERGE (s)-[:HAS_GENERATED_TEST]->(t)
                    """,
                    test_file.model_dump(mode="json"),
                )
            session.run(
                """
                MERGE (s:System {system_name: $system_name})
                MERGE (t:GeneratedTest {test_file_id: $test_file_id})
                SET t.file_path = coalesce(t.file_path, $file_path),
                    t.version = coalesce(t.version, $version)
                MERGE (r:TestRun {result_id: $result_id})
                SET r.run_id = $run_id,
                    r.system_name = $system_name,
                    r.version = $version,
                    r.file_path = $file_path,
                    r.status = $status,
                    r.exit_code = $exit_code,
                    r.passed = $passed,
                    r.failed = $failed,
                    r.skipped = $skipped,
                    r.blocked = $blocked,
                    r.failure_category = $failure_category,
                    r.failure_reason = $failure_reason,
                    r.dependency_blockers = $dependency_blockers,
                    r.execution_scope = $execution_scope,
                    r.xml_report_path = $xml_report_path,
                    r.duration_seconds = $duration_seconds,
                    r.created_at = $created_at
                MERGE (s)-[:HAS_GENERATED_TEST]->(t)
                MERGE (t)-[:HAS_TEST_RUN]->(r)
                """,
                result.model_dump(mode="json"),
            )

    @staticmethod
    def _upsert_coverage_link(
        session: Any,
        *,
        test_file: GeneratedTestFileRecord,
        coverage: CoverageRecord,
    ) -> None:
        session.run(
            """
            MATCH (t:GeneratedTest {test_file_id: $test_file_id})
            MERGE (c:Coverage {coverage_id: $coverage_id})
            SET c.requirement_id = $requirement_id,
                c.system_name = $system_name,
                c.use_case = $use_case,
                c.test_scenario = $test_scenario,
                c.automation_feasibility = $automation_feasibility,
                c.priority = $priority,
                c.coverage_status = $coverage_status,
                c.document_id = $document_id,
                c.version = $version,
                c.chunk_id = $chunk_id,
                c.fact_id = $fact_id,
                c.semantic_key = $semantic_key,
                c.impact_status = $impact_status,
                c.lifecycle_status = $lifecycle_status,
                c.previous_coverage_id = $previous_coverage_id,
                c.superseded_by = $superseded_by,
                c.scenario_index = $scenario_index,
                c.source_hash = $source_hash
            MERGE (t)-[:IMPLEMENTS_COVERAGE]->(c)
            """,
            {
                "test_file_id": test_file.test_file_id,
                "system_name": test_file.system_name,
                **coverage.model_dump(mode="json"),
            },
        )
        if coverage.requirement_id:
            session.run(
                """
                MATCH (c:Coverage {coverage_id: $coverage_id})
                MERGE (r:Requirement {requirement_id: $requirement_id})
                SET r.version = coalesce(r.version, $version),
                    r.document_id = coalesce(r.document_id, $document_id),
                    r.chunk_id = coalesce(r.chunk_id, $chunk_id)
                MERGE (c)-[:COVERS_REQUIREMENT]->(r)
                """,
                coverage.model_dump(mode="json"),
            )
        if coverage.chunk_id:
            session.run(
                """
                MATCH (c:Coverage {coverage_id: $coverage_id})
                MATCH (chunk:Chunk {chunk_id: $chunk_id})
                MERGE (c)-[:SUPPORTED_BY_CHUNK]->(chunk)
                """,
                {
                    "coverage_id": coverage.coverage_id,
                    "chunk_id": coverage.chunk_id,
                },
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
                f.semantic_key = $semantic_key,
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
        elif fact.requirement_id:
            session.run(
                """
                MATCH (f:Fact {fact_id: $fact_id})
                MERGE (r:Requirement {requirement_id: $requirement_id})
                SET r.system_name = $system_name,
                    r.status = $status,
                    r.version = $version
                MERGE (f)-[:TRACES_TO_REQUIREMENT]->(r)
                """,
                {
                    "fact_id": fact.fact_id,
                    "requirement_id": fact.requirement_id,
                    "system_name": fact.system_name,
                    "status": fact.status.value,
                    "version": fact.version,
                },
            )
        if fact.fact_type == "threshold":
            sensor = str(fact.metadata.get("sensor") or "").strip().lower()
            if sensor:
                Neo4jGraphStore._upsert_typed_entity(
                    session,
                    fact=fact,
                    label="Sensor",
                    entity_type="sensor",
                    entity_id=f"sensor:{sensor}",
                    name=sensor,
                    fact_relationship="THRESHOLD_FOR",
                )
        elif fact.fact_type == "protocol_detail":
            protocol = str(fact.metadata.get("protocol") or "").strip()
            if protocol:
                Neo4jGraphStore._upsert_typed_entity(
                    session,
                    fact=fact,
                    label="Protocol",
                    entity_type="protocol",
                    entity_id=f"protocol:{protocol.lower()}",
                    name=protocol,
                    fact_relationship="DETAILS_PROTOCOL",
                )
        elif fact.fact_type in {"sensor", "protocol", "device", "topic", "test"}:
            label_by_type = {
                "sensor": "Sensor",
                "protocol": "Protocol",
                "device": "Device",
                "topic": "Topic",
                "test": "TestCase",
            }
            relationship_by_type = {
                "sensor": "MENTIONS",
                "protocol": "IMPLEMENTS_PROTOCOL",
                "device": "MENTIONS",
                "topic": "USES_TOPIC",
                "test": "VERIFIED_BY",
            }
            Neo4jGraphStore._upsert_typed_entity(
                session,
                fact=fact,
                label=label_by_type[fact.fact_type],
                entity_type=fact.fact_type,
                entity_id=f"{fact.fact_type}:{fact.value.lower()}",
                name=fact.value,
                fact_relationship=relationship_by_type[fact.fact_type],
            )

    @staticmethod
    def _upsert_typed_entity(
        session: Any,
        *,
        fact: FactRecord,
        label: str,
        entity_type: str,
        entity_id: str,
        name: str,
        fact_relationship: str,
    ) -> None:
        if label not in {"Sensor", "Protocol", "Device", "Topic", "TestCase"}:
            raise ValueError(f"Unsupported graph entity label: {label}")
        if fact_relationship not in {
            "MENTIONS",
            "THRESHOLD_FOR",
            "DETAILS_PROTOCOL",
            "IMPLEMENTS_PROTOCOL",
            "USES_TOPIC",
            "VERIFIED_BY",
        }:
            raise ValueError(f"Unsupported graph relationship: {fact_relationship}")
        session.run(
            f"""
            MATCH (c:Chunk {{chunk_id: $chunk_id}})
            MATCH (f:Fact {{fact_id: $fact_id}})
            MERGE (e:Entity {{entity_id: $entity_id}})
            SET e:{label}
            SET e.name = $name,
                e.entity_type = $entity_type,
                e.status = $status,
                e.version = $version,
                e.system_name = $system_name
            MERGE (c)-[:MENTIONS]->(e)
            MERGE (f)-[:{fact_relationship}]->(e)
            """,
            {
                "chunk_id": fact.chunk_id,
                "fact_id": fact.fact_id,
                "entity_id": entity_id,
                "name": name,
                "entity_type": entity_type,
                "status": fact.status.value,
                "version": fact.version,
                "system_name": fact.system_name,
            },
        )
