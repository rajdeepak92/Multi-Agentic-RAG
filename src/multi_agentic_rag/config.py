"""Configuration loaded from environment and .env files."""

from functools import lru_cache
from pathlib import Path

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

    chroma_path: Path = Field(default=Path(".multi_agentic_rag/chroma"))
    sqlite_db_path: Path = Field(default=Path(".multi_agentic_rag/registry.db"))

    default_embedding_model: str = Field(default="BAAI/bge-m3")
    default_reranker_model: str = Field(default="BAAI/bge-reranker-v2-m3")
    default_llm_model: str = Field(default="gpt-5.5")

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
