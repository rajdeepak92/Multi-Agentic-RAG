import pytest

from multi_agentic_rag.models import (
    CoverageRecord,
    DocumentStatus,
    FactRecord,
    GeneratedTestFileRecord,
    TestRunResultRecord,
)
from multi_agentic_rag.config import Settings
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore


def test_typed_entity_upsert_merges_base_entity_before_setting_type_label() -> None:
    session = RecordingSession()
    fact = FactRecord(
        fact_id="fact_protocol_modbus",
        fact_key="protocol:modbus",
        fact_type="protocol",
        value="Modbus",
        document_id="doc_v1",
        chunk_id="chunk_v1",
        system_name="PROJECT_1",
        version="v1",
        status=DocumentStatus.ACTIVE,
        evidence="Controller uses Modbus polling.",
    )

    Neo4jGraphStore._upsert_typed_entity(
        session,
        fact=fact,
        label="Protocol",
        entity_type="protocol",
        entity_id="protocol:modbus",
        name="Modbus",
        fact_relationship="IMPLEMENTS_PROTOCOL",
    )

    query, params = session.runs[0]
    assert "MERGE (e:Entity {entity_id: $entity_id})" in query
    assert "MERGE (e:Entity:Protocol" not in query
    assert "SET e:Protocol" in query
    assert params["entity_id"] == "protocol:modbus"


def test_neo4j_auth_rejects_partial_credentials() -> None:
    store = Neo4jGraphStore(
        Settings(
            neo4j_uri="bolt://localhost:7687",
            neo4j_username="neo4j",
            neo4j_password="",
        )
    )

    with pytest.raises(ValueError, match="NEO4J_USERNAME and NEO4J_PASSWORD"):
        store._auth()


def test_neo4j_auth_allows_unauthenticated_configuration() -> None:
    store = Neo4jGraphStore(
        Settings(
            neo4j_uri="bolt://localhost:7687",
            neo4j_username="",
            neo4j_password="",
        )
    )

    assert store._auth() is None


def test_generated_test_graph_links_coverage_and_requirement() -> None:
    session = RecordingSession()
    store = Neo4jGraphStore(Settings(neo4j_uri="bolt://localhost:7687"))
    store.session = lambda: session  # type: ignore[method-assign]
    test_file = GeneratedTestFileRecord(
        test_file_id="test_file_1",
        run_id="coverage_run_1",
        system_name="PROJECT_1",
        version="v1",
        scope_hash="scope_1",
        file_path="generated/project_1/brd_v1/test_project_1.py",
        tracking_file_path="generated/project_1/brd_v1/test_project_1.json",
        harness_file_paths=[],
        status="ready",
        coverage_ids=["coverage_1"],
        created_at="2026-06-12T00:00:00+00:00",
        updated_at="2026-06-12T00:00:00+00:00",
    )
    coverage = CoverageRecord(
        coverage_id="coverage_1",
        requirement_id="REQ-1",
        use_case="Validate requirement",
        test_scenario="Verify REST status behavior",
        automation_feasibility="dependency_audit_required",
        priority="high",
        coverage_status="planned",
        evidence=["REQ-1 The controller shall expose REST GET /api/status."],
        document_id="doc_1",
        version="v1",
        chunk_id="chunk_1",
        scenario_index=1,
        source_hash="hash_1",
    )

    store.upsert_generated_test_graph(test_file=test_file, coverage_records=[coverage])

    queries = "\n".join(query for query, _ in session.runs)
    assert "MERGE (t:GeneratedTest {test_file_id: $test_file_id})" in queries
    assert "MERGE (t)-[:IMPLEMENTS_COVERAGE]->(c)" in queries
    assert "MERGE (c)-[:COVERS_REQUIREMENT]->(r)" in queries
    assert "MERGE (c)-[:SUPPORTED_BY_CHUNK]->(chunk)" in queries


def test_test_run_graph_links_result_to_generated_test() -> None:
    session = RecordingSession()
    store = Neo4jGraphStore(Settings(neo4j_uri="bolt://localhost:7687"))
    store.session = lambda: session  # type: ignore[method-assign]
    result = TestRunResultRecord(
        result_id="result_1",
        test_file_id="test_file_1",
        run_id="coverage_run_1",
        system_name="PROJECT_1",
        version="v1",
        file_path="generated/project_1/brd_v1/test_project_1.py",
        status="blocked",
        exit_code=0,
        passed=0,
        failed=0,
        skipped=1,
        failure_category="PROTOCOL_UNAVAILABLE",
        failure_reason="Blocked because REST API base URL is not configured",
        dependency_blockers=["Blocked because REST API base URL is not configured"],
        output="blocked",
        created_at="2026-06-12T00:00:00+00:00",
    )

    store.upsert_test_run_graph(result=result)

    query, params = session.runs[0]
    assert "MERGE (r:TestRun {result_id: $result_id})" in query
    assert "MERGE (t)-[:HAS_TEST_RUN]->(r)" in query
    assert params["failure_category"] == "PROTOCOL_UNAVAILABLE"


class RecordingSession:
    def __init__(self) -> None:
        self.runs: list[tuple[str, dict]] = []

    def __enter__(self) -> "RecordingSession":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def run(self, query: str, params: dict | None = None) -> None:
        self.runs.append((query, params or {}))
