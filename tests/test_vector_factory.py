from pathlib import Path

from multi_agentic_rag.config import Settings
from multi_agentic_rag.storage.chroma_store import ChromaVectorStore
from multi_agentic_rag.storage.vector_factory import select_vector_store
from multi_agentic_rag.storage.weaviate_store import WeaviateVectorStore


def test_auto_vector_provider_uses_chroma_without_weaviate_url(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        neo4j_uri=None,
        vector_store_provider="auto",
        weaviate_url=None,
    )

    selection = select_vector_store(settings)

    assert selection.provider == "chroma"
    assert isinstance(selection.store, ChromaVectorStore)


def test_auto_vector_provider_uses_weaviate_when_url_is_configured(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        neo4j_uri=None,
        vector_store_provider="auto",
        weaviate_url="http://127.0.0.1:8080",
    )

    selection = select_vector_store(settings)

    assert selection.provider == "weaviate"
    assert isinstance(selection.store, WeaviateVectorStore)


def test_weaviate_provider_requires_url(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        neo4j_uri=None,
        vector_store_provider="weaviate",
        weaviate_url=None,
    )

    try:
        select_vector_store(settings)
    except RuntimeError as exc:
        assert "WEAVIATE_URL" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for missing WEAVIATE_URL")
