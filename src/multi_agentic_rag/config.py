"""Configuration loaded from environment and .env files."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for local-first ingestion and explicit managed target mode."""

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
    marag_target_mode: Literal["local", "target-graphrag"] = Field(default="local")
    allow_local_dev_mode: bool = Field(default=True)

    neo4j_uri: str | None = Field(default="bolt://127.0.0.1:7687")
    neo4j_username: str = Field(default="neo4j")
    neo4j_password: str = Field(default="password12345")
    neo4j_database: str | None = Field(default="neo4j")
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
    registry_provider: Literal["postgresql", "sqlite"] = Field(default="sqlite")
    postgres_dsn: str | None = Field(default=None)
    object_store_path: Path = Field(default=Path(".multi_agentic_rag/objects"))

    vector_store_provider: Literal["auto", "weaviate", "chroma"] = Field(
        default="chroma"
    )
    weaviate_url: str | None = Field(default=None)
    weaviate_api_key: str | None = Field(default=None)
    weaviate_collection: str = Field(default="MultiAgenticRagChunk")
    weaviate_hybrid_alpha: float = Field(default=0.65)

    keyword_index_enabled: bool = Field(default=True)

    default_embedding_model: str = Field(default="BAAI/bge-m3")
    default_reranker_model: str = Field(default="BAAI/bge-reranker-v2-m3")
    embedding_provider: Literal["hash", "huggingface"] = Field(default="huggingface")
    reranker_provider: Literal["none", "huggingface"] = Field(default="huggingface")
    hash_embedding_dimensions: int = Field(default=384)
    graphrag_required: bool = Field(default=True)

    llm_provider: Literal["none", "openai", "azure_openai"] = Field(default="none")
    default_llm_model: str = Field(default="gpt-4.1-mini")
    azure_openai_endpoint: str | None = Field(default=None)
    azure_openai_api_key: str | None = Field(default=None)
    azure_openai_deployment: str | None = Field(default=None)
    azure_openai_api_version: str = Field(default="2025-04-01-preview")

    enable_pdf_ocr: bool = Field(default=False)
    tesseract_cmd: str | None = Field(default=None)

    generated_test_execution_mode: Literal["mock", "simulator", "real", "auto"] = Field(
        default="auto"
    )
    simulator_config_path: Path | None = Field(default=None)
    rest_simulator_enabled: bool = Field(default=False)
    mqtt_simulator_enabled: bool = Field(default=False)
    modbus_host: str | None = Field(default=None)
    mqtt_broker_url: str | None = Field(default=None)
    can_interface: str | None = Field(default=None)
    rest_api_base_url: str | None = Field(default=None)
    robot_generation_enabled: bool = Field(default=False)

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
