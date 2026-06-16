from multi_agentic_rag.config import Settings


def test_settings_default_to_local_first_ingestion() -> None:
    settings = Settings(_env_file=None)

    assert settings.multi_agentic_rag_profile == "local"
    assert settings.marag_target_mode == "local"
    assert settings.allow_local_dev_mode is True
    assert settings.registry_provider == "sqlite"
    assert settings.vector_store_provider == "chroma"
    assert settings.neo4j_uri == "bolt://127.0.0.1:7687"
    assert settings.neo4j_database == "neo4j"
    assert settings.llm_provider == "none"
    assert settings.graphrag_required is True
    assert settings.default_embedding_model == "BAAI/bge-m3"
    assert settings.default_reranker_model == "BAAI/bge-reranker-v2-m3"
