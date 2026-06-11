"""Configuration loaded from environment and .env files."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the local-first package."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: str | None = Field(default=None)
    hf_token: str | None = Field(default=None)
    hf_home: Path = Field(default=Path(".cache/huggingface"))
    hf_hub_cache: Path = Field(default=Path(".cache/huggingface/hub"))

    multi_agentic_rag_home: Path = Field(default=Path(".multi_agentic_rag"))
    multi_agentic_rag_profile: str = Field(default="local")

    neo4j_uri: str | None = Field(default="bolt://localhost:7687")
    neo4j_username: str = Field(default="neo4j")
    neo4j_password: str = Field(default="password12345")
    neo4j_database: str | None = Field(default=None)
    neo4j_host: str = Field(default="127.0.0.1")
    neo4j_bolt_port: int = Field(default=7687)
    neo4j_browser_port: int = Field(default=7474)
    neo4j_dbms_home: Path | None = Field(default=None)
    neo4j_java_home: Path | None = Field(default=None)
    neo4j_desktop_data_path: Path | None = Field(default=None)
    neo4j_dumps_dir: Path | None = Field(default=None)
    neo4j_import_dir: Path | None = Field(default=None)

    chroma_path: Path = Field(default=Path(".multi_agentic_rag/chroma"))
    sqlite_db_path: Path = Field(default=Path(".multi_agentic_rag/registry.db"))
    object_store_path: Path = Field(default=Path(".multi_agentic_rag/objects"))

    vector_store_provider: Literal["auto", "weaviate", "chroma"] = Field(default="auto")
    weaviate_url: str | None = Field(default=None)
    weaviate_api_key: str | None = Field(default=None)
    weaviate_collection: str = Field(default="MultiAgenticRagChunk")
    weaviate_hybrid_alpha: float = Field(default=0.65)

    keyword_index_enabled: bool = Field(default=True)

    default_embedding_model: str = Field(default="BAAI/bge-m3")
    default_reranker_model: str = Field(default="BAAI/bge-reranker-v2-m3")
    embedding_provider: Literal["hash", "huggingface"] = Field(default="hash")

    llm_provider: Literal["none", "openai", "azure_openai"] = Field(default="none")
    default_llm_model: str = Field(default="gpt-5.5")
    azure_openai_endpoint: str | None = Field(default=None)
    azure_openai_api_key: str | None = Field(default=None)
    azure_openai_deployment: str | None = Field(default=None)

    enable_pdf_ocr: bool = Field(default=False)
    tesseract_cmd: str | None = Field(default=None)

    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)

    mcp_enabled: bool = Field(default=False)
    mcp_transport: str = Field(default="stdio")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings loaded from the current process environment."""

    return Settings()


def reload_settings() -> Settings:
    """Clear and reload settings. Mostly useful for tests."""

    get_settings.cache_clear()
    return get_settings()
