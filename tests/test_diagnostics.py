from multi_agentic_rag.config import Settings
from multi_agentic_rag.utils.diagnostics import (
    _check_embedding_provider,
    _check_hf_token,
    _check_neo4j,
    _check_openai_key,
    _check_weaviate,
)


def test_disabled_optional_providers_do_not_warn_for_missing_credentials() -> None:
    settings = Settings(
        llm_provider="none",
        embedding_provider="hash",
        vector_store_provider="chroma",
        registry_provider="sqlite",
        allow_local_dev_mode=True,
        marag_target_mode="local",
        graphrag_required=False,
        openai_api_key=None,
        hf_token=None,
        weaviate_url=None,
    )

    assert _check_openai_key(settings).status == "PASS"
    assert _check_hf_token(settings).status == "PASS"
    assert _check_weaviate(settings).status == "PASS"


def test_hash_embedding_provider_is_warned_as_test_only() -> None:
    settings = Settings(
        embedding_provider="hash",
        allow_local_dev_mode=True,
        marag_target_mode="local",
        graphrag_required=False,
    )

    check = _check_embedding_provider(settings)

    assert check.status == "WARN"
    assert "deterministic tests" in check.detail


def test_graphrag_required_makes_missing_neo4j_a_failure() -> None:
    settings = Settings(neo4j_uri=None, graphrag_required=True)

    check = _check_neo4j(settings)

    assert check.status == "FAIL"
    assert "NEO4J_URI" in check.detail
