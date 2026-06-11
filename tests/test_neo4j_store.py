import pytest

from multi_agentic_rag.models import DocumentStatus, FactRecord
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


class RecordingSession:
    def __init__(self) -> None:
        self.runs: list[tuple[str, dict]] = []

    def run(self, query: str, params: dict | None = None) -> None:
        self.runs.append((query, params or {}))
