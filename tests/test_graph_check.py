from multi_agentic_rag.config import Settings
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore
from multi_agentic_rag.workflows import GRAPH_CHECK_SYSTEM_NAME, run_graph_check


def test_graph_check_uses_temp_node_with_mocked_driver(tmp_path) -> None:
    driver = FakeDriver()
    store = Neo4jGraphStore(
        Settings(
            multi_agentic_rag_home=tmp_path / ".runtime",
            sqlite_db_path=tmp_path / ".runtime" / "registry.db",
            chroma_path=tmp_path / ".runtime" / "chroma",
            neo4j_uri="bolt://fake:7687",
        )
    )
    store._driver = driver

    result = run_graph_check(graph_store=store)

    assert result.success
    assert result.status == "PASS"
    assert driver.verified
    assert any(GRAPH_CHECK_SYSTEM_NAME in str(params) for _, params in driver.session_obj.runs)
    assert any("DETACH DELETE" in query for query, _ in driver.session_obj.runs)


def test_graph_store_uses_configured_database_for_sessions(tmp_path) -> None:
    driver = FakeDriver()
    store = Neo4jGraphStore(
        Settings(
            multi_agentic_rag_home=tmp_path / ".runtime",
            sqlite_db_path=tmp_path / ".runtime" / "registry.db",
            chroma_path=tmp_path / ".runtime" / "chroma",
            neo4j_uri="bolt://fake:7687",
            neo4j_database="neo4j",
        )
    )
    store._driver = driver

    with store.session():
        pass

    assert driver.session_kwargs == [{"database": "neo4j"}]


class FakeDriver:
    def __init__(self) -> None:
        self.verified = False
        self.closed = False
        self.session_obj = FakeSession()
        self.session_kwargs = []

    def verify_connectivity(self) -> None:
        self.verified = True

    def session(self, **kwargs):
        self.session_kwargs.append(kwargs)
        return self.session_obj

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self) -> None:
        self.runs = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def run(self, query, params=None):
        self.runs.append((query, params or {}))
        if "RETURN count(s) AS count" in query:
            return FakeResult({"count": 1})
        return FakeResult(None)


class FakeResult:
    def __init__(self, record):
        self.record = record

    def single(self):
        return self.record
