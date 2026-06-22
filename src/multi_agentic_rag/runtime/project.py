"""Repository-root initialization and resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from multi_agentic_rag.common_defs import (
    BASE_CONFIG_NAME,
    DOCUMENTS_DIR_NAME,
    GENERATED_DIR_NAME,
    GLOBAL_CACHE_DIR_NAME,
)
from multi_agentic_rag.exceptions import ConfigError

DEFAULT_BASE_CONFIG: dict[str, Any] = {
    "config_schema_version": 1,
    "secrets": {
        "postgres_dsn_env": "POSTGRES_DSN",
        "openai_api_key_env": "OPENAI_API_KEY",
        "hf_token_env": "HF_TOKEN",
        "gemini_api_key_env": "GEMINI_API_KEY",
        "neo4j_password_env": "NEO4J_PASSWORD",
    },
    "paths": {
        "documents_dir": "documents",
        "cache_dir": ".global_cache",
        "generated_dir": "generated",
    },
    "lexical": {
        "backend": "pg_textsearch",
        "native_fts_allowed": False,
    },
    "embeddings": {
        "provider": "sentence_transformers",
        "model": "BAAI/bge-m3",
        "device": "cuda",
        "dimension": 1024,
        "normalize": True,
        "distance_metric": "cosine",
        "prompt_profile": "default",
    },
    "reranking": {
        "provider": "none",
        "model": None,
        "device": "cuda",
    },
    "reasoning": {
        "provider": "hf",
        "openai_model": "gpt-5.5",
        "openai_effort": "medium",
        "openai_store_responses": False,
        "hf_model": "Qwen/Qwen3-0.6B",
        "hf_device": "cuda",
        "hf_dtype": "auto",
        "hf_answer_mode": "deterministic",
        "hf_max_new_tokens": 512,
        "hf_validation_max_new_tokens": 256,
        "hf_timeout_seconds": 120,
        "hf_temperature": 0.0,
        "hf_top_p": 0.8,
        "hf_top_k": 20,
        "hf_enable_thinking": False,
        "gemini_model": "gemini-2.5-pro",
        "structured_retries": 1,
    },
    "ingestion": {
        "recursive": True,
        "atomic_batch": False,
        "chunk_size": 1200,
        "chunk_overlap": 160,
        "enable_pdf_ocr": False,
        "tesseract_cmd": None,
        "supported_extensions": [".pdf", ".docx", ".txt", ".md", ".markdown"],
    },
    "neo4j": {
        "uri": "bolt://127.0.0.1:7687",
        "username": "neo4j",
        "database": "neo4j",
        "graphrag_required": True,
    },
    "chroma": {
        "collection": "multi_agentic_rag_chunks",
        "allow_legacy_without_fingerprint": False,
    },
    "logging": {
        "level": "INFO",
    },
    "postgres": {
        "ssl_mode": "require",
        "connect_timeout_seconds": 10,
        "command_timeout_seconds": 60,
        "statement_timeout_ms": 60000,
        "pool_size": 5,
        "max_overflow": 5,
        "pool_recycle_seconds": 1800,
        "pool_pre_ping": True,
        "retry_count": 2,
        "retry_backoff_seconds": 1.0,
    },
}


def initialize_project_root(project_root: Path, *, force: bool = False) -> Path:
    """Create the root config and runtime directories."""

    root = project_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    _assert_writable(root)

    config_path = root / BASE_CONFIG_NAME
    if force or not config_path.exists():
        config_path.write_text(
            json.dumps(DEFAULT_BASE_CONFIG, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    for child in (DOCUMENTS_DIR_NAME, GLOBAL_CACHE_DIR_NAME, GENERATED_DIR_NAME):
        (root / child).mkdir(parents=True, exist_ok=True)
    _update_gitignore(root)
    return root


def resolve_project_root(
    explicit_project_root: Path | None = None,
    *,
    cwd: Path | None = None,
    require: bool = True,
) -> Path | None:
    """Resolve the runtime project root from an explicit path or cwd."""

    root: Path | None
    if explicit_project_root is not None:
        root = explicit_project_root.expanduser().resolve()
    else:
        current = (cwd or Path.cwd()).expanduser().resolve()
        root = _find_project_root(current)

    if root is None:
        if require:
            raise ConfigError(
                "No project root found. Run commands from the repository root "
                "containing base_config.json or pyproject.toml."
            )
        return None
    return root


def _assert_writable(path: Path) -> None:
    probe = path / ".multi-agentic-rag-write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
    finally:
        if probe.exists():
            probe.unlink()


def _update_gitignore(root: Path) -> None:
    gitignore = root / ".gitignore"
    required = ["/.global_cache/", "/generated/"]
    existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    missing = [line for line in required if line not in existing]
    if not missing:
        return
    if existing and existing[-1].strip():
        existing.append("")
    existing.extend(missing)
    gitignore.write_text("\n".join(existing) + "\n", encoding="utf-8")


def _find_project_root(start: Path) -> Path | None:
    candidates = [start, *start.parents]
    for candidate in candidates:
        if (candidate / BASE_CONFIG_NAME).exists():
            return candidate
    for candidate in candidates:
        if (candidate / "pyproject.toml").exists() and (
            candidate / "src" / "multi_agentic_rag"
        ).exists():
            return candidate
    return None
