"""Environment-backed settings."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from multi_agentic_rag.exceptions import ConfigError

PROJECT_CACHE_PATH_DEFAULTS = {
    "project_root": Path("."),
    "global_cache_dir": Path(".global_cache"),
    "model_cache_dir": Path(".global_cache/models"),
    "database_cache_dir": Path(".global_cache/db"),
    "vectorstore_cache_dir": Path(".global_cache/vectorstore"),
    "graph_cache_dir": Path(".global_cache/neo4j"),
    "hf_home": Path(".global_cache/models/huggingface"),
    "transformers_cache": Path(".global_cache/models/transformers"),
    "sentence_transformers_home": Path(".global_cache/models/sentence_transformers"),
    "torch_home": Path(".global_cache/models/torch"),
    "hf_reason_cache_dir": Path(".global_cache/models/hf_reasoning"),
    "chroma_path": Path(".global_cache/vectorstore/chroma"),
    "multi_agentic_rag_home": Path(".global_cache/runtime"),
    "object_store_path": Path(".global_cache/runtime/objects"),
    "document_store_path": Path(".global_cache/runtime/documents"),
    "manifest_store_path": Path(".global_cache/runtime/manifests"),
}

MODEL_CACHE_ENV_FIELDS = {
    "hf_home": "HF_HOME",
    "transformers_cache": "TRANSFORMERS_CACHE",
    "sentence_transformers_home": "SENTENCE_TRANSFORMERS_HOME",
    "torch_home": "TORCH_HOME",
}


class RuntimePaths(BaseSettings):
    """Resolved runtime directories.

    Attributes:
        home: Base runtime directory.
        documents: Managed source-document directory.
        objects: Reserved object-storage directory for future derived artifacts.
        manifests: JSONL chunk-manifest directory.
        chroma: Persistent ChromaDB directory.
    """

    home: Path
    documents: Path
    objects: Path
    manifests: Path
    chroma: Path


class Settings(BaseSettings):
    """Runtime settings for the GraphRAG-only platform.

    Values load from process environment and `.env`. The names mirror `.env.example` so
    operators can copy the template and fill in service-specific values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    postgres_dsn: str | None = Field(default=None)

    project_root: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["project_root"])
    global_cache_dir: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["global_cache_dir"])
    model_cache_dir: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["model_cache_dir"])
    database_cache_dir: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["database_cache_dir"])
    vectorstore_cache_dir: Path = Field(
        default=PROJECT_CACHE_PATH_DEFAULTS["vectorstore_cache_dir"]
    )
    graph_cache_dir: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["graph_cache_dir"])
    hf_home: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["hf_home"])
    transformers_cache: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["transformers_cache"])
    sentence_transformers_home: Path = Field(
        default=PROJECT_CACHE_PATH_DEFAULTS["sentence_transformers_home"]
    )
    torch_home: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["torch_home"])

    neo4j_uri: str | None = Field(default="bolt://127.0.0.1:7687")
    neo4j_username: str = Field(default="neo4j")
    neo4j_password: str | None = Field(default=None)
    neo4j_database: str | None = Field(default="neo4j")
    graphrag_required: bool = Field(default=True)

    chroma_path: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["chroma_path"])
    chroma_collection: str = Field(default="multi_agentic_rag_chunks_minilm_l6_v1")
    chroma_allow_legacy_without_fingerprint: bool = Field(default=False)

    embedding_provider: Literal["hash", "sentence_transformers"] = Field(
        default="sentence_transformers"
    )
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
    embedding_model_revision: str = Field(default="default")
    embedding_dimensions: int = Field(default=384)
    embedding_device: str = Field(default="auto")
    embedding_normalize: bool = Field(default=True)
    embedding_distance_metric: str = Field(default="cosine")
    embedding_prompt_profile: str = Field(default="default")
    hf_token: str | None = Field(default=None)
    reranker_provider: Literal["none", "sentence_transformers"] = Field(default="none")
    reranker_model: str | None = Field(default=None)
    reranker_device: str = Field(default="auto")

    openai_api_key: str | None = Field(default=None)
    reasoning_provider: Literal["openai", "hf", "huggingface", "gemini"] = Field(
        default="openai"
    )
    openai_reasoning_model: str = Field(default="gpt-5.5")
    openai_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = Field(
        default="medium"
    )
    openai_store_responses: bool = Field(default=False)
    gemini_api_key: str | None = Field(default=None)
    gemini_reasoning_model: str = Field(default="gemini-2.5-pro")
    structured_generation_retry_count: int = Field(default=1)
    hf_reason_model: str = Field(default="Qwen/Qwen3-0.6B")
    hf_reason_device: str = Field(default="auto")
    hf_reason_dtype: str = Field(default="auto")
    hf_reason_max_new_tokens: int = Field(default=512)
    hf_reason_validation_max_new_tokens: int = Field(default=256)
    hf_reason_timeout_seconds: float = Field(default=120.0)
    hf_reason_answer_mode: Literal["deterministic", "extractive", "generative"] = Field(
        default="deterministic"
    )
    hf_reason_temperature: float = Field(default=0.0)
    hf_reason_top_p: float = Field(default=0.8)
    hf_reason_top_k: int = Field(default=20)
    hf_reason_cache_dir: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["hf_reason_cache_dir"])
    hf_reason_enable_thinking: bool = Field(default=False)
    user_story_output_dir: Path = Field(default=Path("generated"))
    active_run_id: str | None = Field(default=None)
    active_run_dir: Path | None = Field(default=None)
    run_results_dir: Path | None = Field(default=None)
    run_log_path: Path | None = Field(default=None)

    multi_agentic_rag_home: Path = Field(
        default=PROJECT_CACHE_PATH_DEFAULTS["multi_agentic_rag_home"]
    )
    object_store_path: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["object_store_path"])
    document_store_path: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["document_store_path"])
    manifest_store_path: Path = Field(default=PROJECT_CACHE_PATH_DEFAULTS["manifest_store_path"])

    chunk_size: int = Field(default=1200)
    chunk_overlap: int = Field(default=160)
    enable_pdf_ocr: bool = Field(default=False)
    tesseract_cmd: str | None = Field(default=None)

    bm25_backend: Literal["pg_textsearch", "postgres_fts"] = Field(default="postgres_fts")
    retrieval_required_sources: tuple[str, ...] = Field(
        default=("postgres", "chroma", "neo4j")
    )
    retrieval_lexical_top_k: int = Field(default=20)
    retrieval_vector_top_k: int = Field(default=20)
    retrieval_graph_top_k: int = Field(default=20)
    retrieval_fusion_top_k: int = Field(default=30)
    retrieval_rerank_top_k: int = Field(default=10)
    retrieval_fusion_strategy: str = Field(default="preserve_current")
    retrieval_reciprocal_rank_constant: int = Field(default=60)
    retrieval_max_retrieval_rounds: int = Field(default=2)
    retrieval_allow_degraded: bool = Field(default=False)
    retrieval_answer_top_k: int = Field(default=10)
    retrieval_answer_max_evidence: int = Field(default=20)
    retrieval_answer_max_snippets: int = Field(default=8)
    user_story_schema_version: str = Field(default="enterprise-user-story-v1")
    user_story_requirement_batch_size: int = Field(default=6)
    user_story_max_stories_per_batch: int = Field(default=8)
    user_story_coverage_required_types: tuple[str, ...] = Field(
        default=("business_rule", "functional", "non_functional", "automation_rule")
    )
    user_story_allow_partial_coverage: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    postgres_connect_timeout_seconds: float = Field(default=10.0)
    postgres_command_timeout_seconds: float = Field(default=60.0)
    postgres_statement_timeout_ms: int = Field(default=60000)
    postgres_pool_size: int = Field(default=5)
    postgres_max_overflow: int = Field(default=5)
    postgres_pool_recycle_seconds: int = Field(default=1800)
    postgres_pool_pre_ping: bool = Field(default=True)
    postgres_retry_count: int = Field(default=2)
    postgres_retry_backoff_seconds: float = Field(default=1.0)
    postgres_ssl_mode: str = Field(default="prefer")

    @field_validator("embedding_provider", mode="before")
    @classmethod
    def _normalize_embedding_provider(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() == "huggingface":
            return "sentence_transformers"
        return value

    @field_validator("reranker_provider", mode="before")
    @classmethod
    def _normalize_reranker_provider(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() == "huggingface":
            return "sentence_transformers"
        return value

    @field_validator("reasoning_provider", mode="before")
    @classmethod
    def _normalize_reasoning_provider(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"huggingface", "hugging_face", "local_hf"}:
                return "hf"
            return normalized
        return value

    @field_validator("retrieval_required_sources", mode="before")
    @classmethod
    def _normalize_required_sources(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return ("postgres", "chroma", "neo4j")
            if stripped.startswith("["):
                import json

                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return tuple(str(item).strip().lower() for item in parsed)
            return tuple(item.strip().lower() for item in stripped.split(",") if item.strip())
        if isinstance(value, list | tuple):
            return tuple(str(item).strip().lower() for item in value)
        return value

    @field_validator("user_story_coverage_required_types", mode="before")
    @classmethod
    def _normalize_coverage_required_types(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return ("business_rule", "functional", "non_functional", "automation_rule")
            if stripped.startswith("["):
                import json

                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return tuple(str(item).strip().lower() for item in parsed)
            return tuple(item.strip().lower() for item in stripped.split(",") if item.strip())
        if isinstance(value, list | tuple):
            return tuple(str(item).strip().lower() for item in value)
        return value

    @field_validator("bm25_backend", mode="before")
    @classmethod
    def _normalize_bm25_backend(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "postgres":
                return "postgres_fts"
            return normalized
        return value

    @field_validator("hf_reason_cache_dir", mode="before")
    @classmethod
    def _normalize_hf_reason_cache_dir(cls, value: object) -> object:
        if value in {"", None}:
            return PROJECT_CACHE_PATH_DEFAULTS["hf_reason_cache_dir"]
        return value

    @field_validator(*PROJECT_CACHE_PATH_DEFAULTS.keys(), mode="before")
    @classmethod
    def _default_blank_project_cache_paths(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> object:
        if value in {"", None}:
            field_name = info.field_name
            if field_name is None:
                return value
            return PROJECT_CACHE_PATH_DEFAULTS[field_name]
        return value

    def ensure_project_cache_paths(self) -> dict[str, Path]:
        """Create project-local cache directories and configure model cache env vars."""

        root = Path(self.project_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        resolved_paths: dict[str, Path] = {}
        for field_name in PROJECT_CACHE_PATH_DEFAULTS:
            raw_path = getattr(self, field_name)
            resolved = (
                root
                if field_name == "project_root"
                else self._resolve_project_path(raw_path)
            )
            setattr(self, field_name, resolved)
            resolved_paths[field_name] = resolved
        for field_name, path in resolved_paths.items():
            if field_name == "project_root":
                continue
            path.mkdir(parents=True, exist_ok=True)
        for field_name, env_name in MODEL_CACHE_ENV_FIELDS.items():
            os.environ[env_name] = str(resolved_paths[field_name])
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
        return resolved_paths

    def _resolve_project_path(self, raw_path: Path) -> Path:
        root = Path(self.project_root).expanduser().resolve()
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = root / path
        resolved = path.resolve()
        if resolved != root and not resolved.is_relative_to(root):
            raise ConfigError(
                f"{resolved} must stay inside PROJECT_ROOT ({root}). "
                "Set PROJECT_ROOT or the cache path to a project-local directory."
            )
        return resolved

    def runtime_paths(self) -> RuntimePaths:
        """Create and return runtime directories.

        Returns:
            RuntimePaths with every directory created if it was missing.
        """

        self.ensure_project_cache_paths()
        paths = RuntimePaths(
            home=self.multi_agentic_rag_home,
            documents=self.document_store_path,
            objects=self.object_store_path,
            manifests=self.manifest_store_path,
            chroma=self.chroma_path,
        )
        for path in (
            paths.home,
            paths.documents,
            paths.objects,
            paths.manifests,
            paths.chroma,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return paths


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings loaded from the current process environment.

    Returns:
        Cached Settings instance loaded from environment and `.env`.
    """

    return Settings()


def reload_settings() -> Settings:
    """Clear and reload settings.

    Returns:
        Fresh Settings instance after clearing the process cache.
    """

    get_settings.cache_clear()
    return get_settings()
