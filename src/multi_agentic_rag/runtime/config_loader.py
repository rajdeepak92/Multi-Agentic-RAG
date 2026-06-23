"""Root config loading and environment projection."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from multi_agentic_rag.common_defs import (
    BASE_CONFIG_NAME,
    GENERATED_DIR_NAME,
    GLOBAL_CACHE_DIR_NAME,
)
from multi_agentic_rag.exceptions import ConfigError
from multi_agentic_rag.runtime.secrets import redact_secrets

PROJECT_PATH_ENV_NAMES = {
    "PROJECT_ROOT",
    "GLOBAL_CACHE_DIR",
    "MODEL_CACHE_DIR",
    "DATABASE_CACHE_DIR",
    "VECTORSTORE_CACHE_DIR",
    "GRAPH_CACHE_DIR",
    "HF_HOME",
    "TRANSFORMERS_CACHE",
    "SENTENCE_TRANSFORMERS_HOME",
    "TORCH_HOME",
    "HF_REASON_CACHE_DIR",
    "CHROMA_PATH",
    "MULTI_AGENTIC_RAG_HOME",
    "DOCUMENT_STORE_PATH",
    "OBJECT_STORE_PATH",
    "MANIFEST_STORE_PATH",
    "USER_STORY_OUTPUT_DIR",
}


@dataclass(frozen=True)
class RuntimeConfigResolution:
    """Resolved project config and projected environment defaults."""

    project_root: Path
    config_path: Path
    config: dict[str, Any]
    applied_env: dict[str, str] = field(default_factory=dict)
    cli_overrides: dict[str, Any] = field(default_factory=dict)

    def redacted(self) -> dict[str, Any]:
        """Return a redacted manifest-friendly representation."""

        return {
            "project_root": str(self.project_root),
            "config_path": str(self.config_path),
            "config": redact_secrets(self.config),
            "applied_env": redact_secrets(self.applied_env),
            "cli_overrides": redact_secrets(self.cli_overrides),
        }


def load_base_config(project_root: Path) -> tuple[Path, dict[str, Any]]:
    """Load root base_config.json if present."""

    config_path = project_root / BASE_CONFIG_NAME
    if not config_path.exists():
        return config_path, {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {config_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"{config_path} must contain a JSON object.")
    return config_path, payload


def load_config_file(config_path: Path) -> tuple[Path, dict[str, Any]]:
    """Load an explicitly selected base config file."""

    path = config_path.expanduser().resolve(strict=False)
    if path.name != BASE_CONFIG_NAME:
        raise ConfigError(f"Config path must point to {BASE_CONFIG_NAME}: {path}")
    if not path.exists():
        return path, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"{path} must contain a JSON object.")
    return path, payload


def apply_project_config(
    project_root: Path,
    *,
    config_path: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> RuntimeConfigResolution:
    """Project root config into environment defaults without rewriting config."""

    env = environ if environ is not None else os.environ
    root = project_root.expanduser().resolve()
    loaded_config_path, config = (
        load_config_file(config_path) if config_path is not None else load_base_config(root)
    )
    if loaded_config_path.parent != root and loaded_config_path.exists():
        raise ConfigError(
            f"{loaded_config_path} is outside PROJECT_ROOT ({root}). "
            "Select a config whose parent is the project root."
        )
    applied: dict[str, str] = {}

    defaults = _env_defaults(root, config, env)
    for key, value in defaults.items():
        if value is None:
            continue
        if key in PROJECT_PATH_ENV_NAMES or key not in env:
            env[key] = str(value)
            applied[key] = str(value)

    for key, value in _cli_env_overrides(cli_overrides or {}).items():
        if value is None:
            continue
        env[key] = str(value)
        applied[key] = str(value)

    return RuntimeConfigResolution(
        project_root=root,
        config_path=loaded_config_path,
        config=config,
        applied_env=applied,
        cli_overrides=cli_overrides or {},
    )


def resolve_config_value(
    name: str,
    *,
    cli_value: Any = None,
    env_name: str | None = None,
    config: dict[str, Any] | None = None,
    default: Any = None,
) -> tuple[Any, str]:
    """Resolve one value using CLI, environment, config, defaults precedence."""

    if cli_value is not None:
        return cli_value, "cli"
    if env_name and os.environ.get(env_name) not in {None, ""}:
        return os.environ[env_name], "environment"
    if config is not None:
        marker = object()
        value = _lookup_dotted(config, name, marker)
        if value is not marker:
            return value, "base_config.json"
    return default, "default"


def _env_defaults(
    project_root: Path,
    config: dict[str, Any],
    env: Mapping[str, str],
) -> dict[str, str | None]:
    paths = _dict(config.get("paths"))
    secrets = _dict(config.get("secrets"))
    postgres = _dict(config.get("postgres"))
    neo4j = _dict(config.get("neo4j"))
    chroma = _dict(config.get("chroma"))
    embeddings = _dict(config.get("embeddings"))
    reranking = _dict(config.get("reranking"))
    reasoning = _dict(config.get("reasoning"))
    retrieval = _dict(config.get("retrieval"))
    ingestion = _dict(config.get("ingestion"))
    user_stories = _dict(config.get("user_stories"))
    lexical = _dict(config.get("lexical"))
    logging = _dict(config.get("logging"))

    cache_dir = _resolve_project_path(
        project_root,
        paths.get("cache_dir", GLOBAL_CACHE_DIR_NAME),
        field_name="paths.cache_dir",
    )
    documents_dir = _resolve_project_path(
        project_root,
        paths.get("documents_dir", "documents"),
        field_name="paths.documents_dir",
    )
    generated_dir = _resolve_project_path(
        project_root,
        paths.get("generated_dir", GENERATED_DIR_NAME),
        field_name="paths.generated_dir",
    )
    model_cache_dir = cache_dir / "models"
    runtime_dir = cache_dir / "runtime"
    defaults: dict[str, str | None] = {
        "PROJECT_ROOT": str(project_root),
        "GLOBAL_CACHE_DIR": str(cache_dir),
        "MODEL_CACHE_DIR": str(model_cache_dir),
        "DATABASE_CACHE_DIR": str(cache_dir / "db"),
        "VECTORSTORE_CACHE_DIR": str(cache_dir / "vectorstore"),
        "GRAPH_CACHE_DIR": str(cache_dir / "neo4j"),
        "HF_HOME": str(model_cache_dir / "huggingface"),
        "TRANSFORMERS_CACHE": str(model_cache_dir / "transformers"),
        "SENTENCE_TRANSFORMERS_HOME": str(model_cache_dir / "sentence_transformers"),
        "TORCH_HOME": str(model_cache_dir / "torch"),
        "HF_REASON_CACHE_DIR": str(model_cache_dir / "hf_reasoning"),
        "CHROMA_PATH": str(cache_dir / "vectorstore" / "chroma"),
        "MULTI_AGENTIC_RAG_HOME": str(runtime_dir),
        "DOCUMENT_STORE_PATH": str(runtime_dir / "documents"),
        "OBJECT_STORE_PATH": str(runtime_dir / "objects"),
        "MANIFEST_STORE_PATH": str(runtime_dir / "manifests"),
        "DOCUMENTS_DIR": str(documents_dir),
        "USER_STORY_OUTPUT_DIR": str(generated_dir),
        "NEO4J_URI": _string_or_none(neo4j.get("uri")),
        "NEO4J_USERNAME": _string_or_none(neo4j.get("username")),
        "NEO4J_DATABASE": _string_or_none(neo4j.get("database")),
        "GRAPHRAG_REQUIRED": _string_or_none(neo4j.get("graphrag_required")),
        "CHROMA_COLLECTION": _string_or_none(chroma.get("collection")),
        "CHROMA_ALLOW_LEGACY_WITHOUT_FINGERPRINT": _string_or_none(
            chroma.get("allow_legacy_without_fingerprint")
        ),
        "BM25_BACKEND": _string_or_none(lexical.get("backend")),
        "EMBEDDING_PROVIDER": _string_or_none(embeddings.get("provider")),
        "EMBEDDING_MODEL": _string_or_none(embeddings.get("model")),
        "EMBEDDING_MODEL_REVISION": _string_or_none(embeddings.get("revision")),
        "EMBEDDING_DIMENSIONS": _string_or_none(embeddings.get("dimension")),
        "EMBEDDING_DEVICE": _string_or_none(embeddings.get("device")),
        "EMBEDDING_NORMALIZE": _string_or_none(embeddings.get("normalize")),
        "EMBEDDING_DISTANCE_METRIC": _string_or_none(embeddings.get("distance_metric")),
        "EMBEDDING_PROMPT_PROFILE": _string_or_none(embeddings.get("prompt_profile")),
        "RERANKER_PROVIDER": _string_or_none(reranking.get("provider")),
        "RERANKER_MODEL": _string_or_none(reranking.get("model")),
        "RERANKER_DEVICE": _string_or_none(reranking.get("device")),
        "REASONING_PROVIDER": _string_or_none(reasoning.get("provider")),
        "OPENAI_REASONING_MODEL": _string_or_none(reasoning.get("openai_model")),
        "OPENAI_REASONING_EFFORT": _string_or_none(reasoning.get("openai_effort")),
        "OPENAI_STORE_RESPONSES": _string_or_none(reasoning.get("openai_store_responses")),
        "HF_REASON_MODEL": _string_or_none(reasoning.get("hf_model")),
        "HF_REASON_DEVICE": _string_or_none(reasoning.get("hf_device")),
        "HF_REASON_DTYPE": _string_or_none(reasoning.get("hf_dtype")),
        "HF_REASON_MAX_NEW_TOKENS": _string_or_none(reasoning.get("hf_max_new_tokens")),
        "HF_REASON_VALIDATION_MAX_NEW_TOKENS": _string_or_none(
            reasoning.get("hf_validation_max_new_tokens")
        ),
        "HF_REASON_TIMEOUT_SECONDS": _string_or_none(
            reasoning.get("hf_timeout_seconds")
        ),
        "HF_REASON_ANSWER_MODE": _string_or_none(reasoning.get("hf_answer_mode")),
        "HF_REASON_TEMPERATURE": _string_or_none(reasoning.get("hf_temperature")),
        "HF_REASON_TOP_P": _string_or_none(reasoning.get("hf_top_p")),
        "HF_REASON_TOP_K": _string_or_none(reasoning.get("hf_top_k")),
        "HF_REASON_ENABLE_THINKING": _string_or_none(
            reasoning.get("hf_enable_thinking")
        ),
        "GEMINI_REASONING_MODEL": _string_or_none(reasoning.get("gemini_model")),
        "STRUCTURED_GENERATION_RETRY_COUNT": _string_or_none(reasoning.get("structured_retries")),
        "RETRIEVAL_REQUIRED_SOURCES": _string_or_none(retrieval.get("required_sources")),
        "RETRIEVAL_LEXICAL_TOP_K": _string_or_none(retrieval.get("lexical_top_k")),
        "RETRIEVAL_VECTOR_TOP_K": _string_or_none(retrieval.get("vector_top_k")),
        "RETRIEVAL_GRAPH_TOP_K": _string_or_none(retrieval.get("graph_top_k")),
        "RETRIEVAL_FUSION_TOP_K": _string_or_none(retrieval.get("fusion_top_k")),
        "RETRIEVAL_RERANK_TOP_K": _string_or_none(retrieval.get("rerank_top_k")),
        "RETRIEVAL_FUSION_STRATEGY": _string_or_none(retrieval.get("fusion_strategy")),
        "RETRIEVAL_RECIPROCAL_RANK_CONSTANT": _string_or_none(
            retrieval.get("reciprocal_rank_constant")
        ),
        "RETRIEVAL_MAX_RETRIEVAL_ROUNDS": _string_or_none(
            retrieval.get("max_retrieval_rounds")
        ),
        "RETRIEVAL_ALLOW_DEGRADED": _string_or_none(
            retrieval.get("allow_degraded_retrieval")
        ),
        "RETRIEVAL_ANSWER_TOP_K": _string_or_none(retrieval.get("answer_top_k")),
        "RETRIEVAL_ANSWER_MAX_EVIDENCE": _string_or_none(
            retrieval.get("answer_max_evidence")
        ),
        "RETRIEVAL_ANSWER_MAX_SNIPPETS": _string_or_none(
            retrieval.get("answer_max_snippets")
        ),
        "USER_STORY_SCHEMA_VERSION": _string_or_none(user_stories.get("schema_version")),
        "USER_STORY_REQUIREMENT_BATCH_SIZE": _string_or_none(
            user_stories.get("requirement_batch_size")
        ),
        "USER_STORY_MAX_STORIES_PER_BATCH": _string_or_none(
            user_stories.get("max_stories_per_batch")
        ),
        "USER_STORY_COVERAGE_REQUIRED_TYPES": _string_or_none(
            user_stories.get("coverage_required_types")
        ),
        "USER_STORY_ALLOW_PARTIAL_COVERAGE": _string_or_none(
            user_stories.get("allow_partial_coverage")
        ),
        "CHUNK_SIZE": _string_or_none(ingestion.get("chunk_size")),
        "CHUNK_OVERLAP": _string_or_none(ingestion.get("chunk_overlap")),
        "ENABLE_PDF_OCR": _string_or_none(ingestion.get("enable_pdf_ocr")),
        "TESSERACT_CMD": _string_or_none(ingestion.get("tesseract_cmd")),
        "LOG_LEVEL": _string_or_none(logging.get("level")),
        "POSTGRES_CONNECT_TIMEOUT_SECONDS": _string_or_none(
            postgres.get("connect_timeout_seconds")
        ),
        "POSTGRES_COMMAND_TIMEOUT_SECONDS": _string_or_none(
            postgres.get("command_timeout_seconds")
        ),
        "POSTGRES_STATEMENT_TIMEOUT_MS": _string_or_none(postgres.get("statement_timeout_ms")),
        "POSTGRES_POOL_SIZE": _string_or_none(postgres.get("pool_size")),
        "POSTGRES_MAX_OVERFLOW": _string_or_none(postgres.get("max_overflow")),
        "POSTGRES_POOL_RECYCLE_SECONDS": _string_or_none(postgres.get("pool_recycle_seconds")),
        "POSTGRES_POOL_PRE_PING": _string_or_none(postgres.get("pool_pre_ping")),
        "POSTGRES_RETRY_COUNT": _string_or_none(postgres.get("retry_count")),
        "POSTGRES_RETRY_BACKOFF_SECONDS": _string_or_none(postgres.get("retry_backoff_seconds")),
        "POSTGRES_SSL_MODE": _string_or_none(postgres.get("ssl_mode")),
    }

    for config_key, target_env in {
        "postgres_dsn_env": "POSTGRES_DSN",
        "openai_api_key_env": "OPENAI_API_KEY",
        "hf_token_env": "HF_TOKEN",
        "gemini_api_key_env": "GEMINI_API_KEY",
        "neo4j_password_env": "NEO4J_PASSWORD",
    }.items():
        source_env_name = secrets.get(config_key)
        if isinstance(source_env_name, str) and env.get(source_env_name):
            defaults[target_env] = env[source_env_name]
    return defaults


def _cli_env_overrides(cli_overrides: dict[str, Any]) -> dict[str, Any]:
    mapping: dict[str, tuple[str, Callable[[Any], Any]]] = {
        "debug": ("LOG_LEVEL", lambda value: "DEBUG" if value else None),
        "model": ("REASONING_PROVIDER", str),
    }
    projected: dict[str, Any] = {}
    for key, value in cli_overrides.items():
        item = mapping.get(key)
        if item is None:
            continue
        env_name, converter = item
        projected[env_name] = converter(value)
    return projected


def _lookup_dotted(payload: dict[str, Any], name: str, default: Any) -> Any:
    current: Any = payload
    for part in name.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list | dict | tuple):
        return json.dumps(value)
    return str(value)


def _resolve_project_path(project_root: Path, value: Any, *, field_name: str) -> Path:
    raw = Path(str(value or ".")).expanduser()
    candidate = raw if raw.is_absolute() else project_root / raw
    resolved = candidate.resolve(strict=False)
    if resolved != project_root and not resolved.is_relative_to(project_root):
        raise ConfigError(
            f"{field_name} resolves outside PROJECT_ROOT: {resolved} "
            f"(PROJECT_ROOT={project_root})."
        )
    return resolved
