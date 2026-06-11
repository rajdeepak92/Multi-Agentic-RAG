from multi_agentic_rag.config import Settings
from multi_agentic_rag.utils.diagnostics import (
    _check_hf_token,
    _check_openai_key,
    _check_weaviate,
)


def test_disabled_optional_providers_do_not_warn_for_missing_credentials() -> None:
    settings = Settings(
        llm_provider="none",
        embedding_provider="hash",
        vector_store_provider="chroma",
        openai_api_key=None,
        hf_token=None,
        weaviate_url=None,
    )

    assert _check_openai_key(settings).status == "PASS"
    assert _check_hf_token(settings).status == "PASS"
    assert _check_weaviate(settings).status == "PASS"
