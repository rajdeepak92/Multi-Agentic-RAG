from pathlib import Path

from multi_agentic_rag.config import Settings
from multi_agentic_rag.models import ChunkRecord, DocumentStatus
from multi_agentic_rag.storage.chroma_store import ChromaVectorStore
from multi_agentic_rag.storage.vector_factory import select_vector_store
from multi_agentic_rag.storage.weaviate_store import WeaviateVectorStore


def test_auto_vector_provider_uses_chroma_without_weaviate_url(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        registry_provider="sqlite",
        allow_local_dev_mode=True,
        marag_target_mode="local",
        graphrag_required=False,
        neo4j_uri=None,
        embedding_provider="hash",
        reranker_provider="none",
        llm_provider="none",
        vector_store_provider="auto",
        weaviate_url=None,
    )

    selection = select_vector_store(settings)

    assert selection.provider == "chroma"
    assert isinstance(selection.store, ChromaVectorStore)
    assert selection.store.embedding_provider == "hash"
    assert selection.store.embedding_model == "multi_agentic_rag_hash_embedding"


def test_auto_vector_provider_uses_weaviate_when_url_is_configured(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        registry_provider="sqlite",
        allow_local_dev_mode=True,
        marag_target_mode="local",
        graphrag_required=False,
        neo4j_uri=None,
        embedding_provider="hash",
        reranker_provider="none",
        llm_provider="none",
        vector_store_provider="auto",
        weaviate_url="http://127.0.0.1:8080",
    )

    selection = select_vector_store(settings)

    assert selection.provider == "weaviate"
    assert isinstance(selection.store, WeaviateVectorStore)
    assert selection.store.embedding_provider == "hash"
    assert selection.store.embedding_model == "multi_agentic_rag_hash_embedding"


def test_weaviate_provider_requires_url(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        registry_provider="sqlite",
        allow_local_dev_mode=True,
        marag_target_mode="local",
        graphrag_required=False,
        neo4j_uri=None,
        embedding_provider="hash",
        reranker_provider="none",
        llm_provider="none",
        vector_store_provider="weaviate",
        weaviate_url=None,
    )

    try:
        select_vector_store(settings)
    except RuntimeError as exc:
        assert "WEAVIATE_URL" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for missing WEAVIATE_URL")


def test_auto_chroma_fallback_is_rejected_when_local_dev_is_disabled(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        registry_provider="postgresql",
        postgres_dsn="postgresql://user:pass@host/db",
        allow_local_dev_mode=False,
        embedding_provider="huggingface",
        vector_store_provider="auto",
        weaviate_url=None,
    )

    try:
        select_vector_store(settings)
    except RuntimeError as exc:
        assert "ALLOW_LOCAL_DEV_MODE=true" in str(exc)
    else:
        raise AssertionError("Expected strict mode to reject Chroma fallback")


def test_hash_embeddings_are_rejected_when_local_dev_is_disabled(tmp_path: Path) -> None:
    settings = Settings(
        multi_agentic_rag_home=tmp_path / ".runtime",
        sqlite_db_path=tmp_path / ".runtime" / "registry.db",
        chroma_path=tmp_path / ".runtime" / "chroma",
        registry_provider="postgresql",
        postgres_dsn="postgresql://user:pass@host/db",
        allow_local_dev_mode=False,
        embedding_provider="hash",
        vector_store_provider="weaviate",
        weaviate_url="https://weaviate.example.com",
    )

    try:
        select_vector_store(settings)
    except RuntimeError as exc:
        assert "ALLOW_LOCAL_DEV_MODE=true" in str(exc)
    else:
        raise AssertionError("Expected strict mode to reject hash embeddings")


def test_vector_metadata_records_embedding_provider_and_model(tmp_path: Path) -> None:
    store = ChromaVectorStore(
        tmp_path / "chroma",
        embedding_provider="huggingface",
        embedding_model="BAAI/bge-m3",
    )
    chunk = ChunkRecord(
        chunk_id="chunk_1",
        document_id="doc_1",
        system_name="PROJECT_1",
        version="v1",
        status=DocumentStatus.ACTIVE,
        source_name="PROJECT_1_BRD_V1.docx",
        page=1,
        section_title="Requirements",
        chunk_index=0,
        content_hash="hash_1",
        text="REQ-1 The controller shall expose REST GET /api/status.",
    )

    metadata = store._metadata(chunk)

    assert metadata["embedding_provider"] == "huggingface"
    assert metadata["embedding_model"] == "BAAI/bge-m3"


def test_weaviate_properties_record_embedding_provider_and_model() -> None:
    store = WeaviateVectorStore(
        url="http://127.0.0.1:8080",
        embedding_provider="huggingface",
        embedding_model="BAAI/bge-m3",
    )
    chunk = ChunkRecord(
        chunk_id="chunk_1",
        document_id="doc_1",
        system_name="PROJECT_1",
        version="v1",
        status=DocumentStatus.ACTIVE,
        source_name="PROJECT_1_BRD_V1.docx",
        page=1,
        section_title="Requirements",
        chunk_index=0,
        content_hash="hash_1",
        text="REQ-1 The controller shall expose REST GET /api/status.",
    )

    properties = store._properties(chunk)

    assert properties["embedding_provider"] == "huggingface"
    assert properties["embedding_model"] == "BAAI/bge-m3"
