"""Runtime diagnostics shared by CLI and FastAPI."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.utils.paths import resolve_path


@dataclass(frozen=True)
class DiagnosticCheck:
    """One doctor check result."""

    name: str
    status: str
    detail: str


def run_diagnostics(settings: Settings | None = None) -> list[DiagnosticCheck]:
    """Run local environment checks without requiring external services."""

    settings = settings or get_settings()
    checks = [
        _check_python_version(),
        _check_dotenv(),
        _check_openai_key(settings),
        _check_hf_token(settings),
        _check_sqlite(settings),
        _check_chroma(settings),
        _check_neo4j(settings),
        _check_fastapi_app_import(),
    ]
    return checks


def _check_python_version() -> DiagnosticCheck:
    version = sys.version_info
    if version >= (3, 12):
        return DiagnosticCheck("Python", "PASS", sys.version.split()[0])
    return DiagnosticCheck("Python", "FAIL", "Python 3.12+ is required.")


def _check_dotenv() -> DiagnosticCheck:
    env_path = find_dotenv(usecwd=True)
    loaded = load_dotenv(env_path, override=False) if env_path else False
    if loaded:
        return DiagnosticCheck(".env", "PASS", f"Loaded {env_path}")
    if env_path:
        return DiagnosticCheck(".env", "PASS", f"Found {env_path}")
    return DiagnosticCheck(".env", "WARN", ".env not found; defaults/environment are being used.")


def _check_openai_key(settings: Settings) -> DiagnosticCheck:
    if settings.openai_api_key:
        return DiagnosticCheck("OPENAI_API_KEY", "PASS", "Configured.")
    return DiagnosticCheck(
        "OPENAI_API_KEY",
        "WARN",
        "Missing. Required only for future LLM-backed generation.",
    )


def _check_hf_token(settings: Settings) -> DiagnosticCheck:
    if settings.hf_token:
        return DiagnosticCheck("HF_TOKEN", "PASS", "Configured.")
    return DiagnosticCheck("HF_TOKEN", "WARN", "Missing. Public Hugging Face models may still work.")


def _check_sqlite(settings: Settings) -> DiagnosticCheck:
    try:
        registry = SQLiteRegistry(settings.sqlite_db_path)
        registry.initialize()
    except Exception as exc:
        return DiagnosticCheck("SQLite registry", "FAIL", str(exc))
    return DiagnosticCheck("SQLite registry", "PASS", str(resolve_path(settings.sqlite_db_path)))


def _check_chroma(settings: Settings) -> DiagnosticCheck:
    try:
        path = resolve_path(settings.chroma_path)
        path.mkdir(parents=True, exist_ok=True)
        importlib.import_module("chromadb")
    except ModuleNotFoundError:
        return DiagnosticCheck("ChromaDB", "WARN", "chromadb is not installed.")
    except Exception as exc:
        return DiagnosticCheck("ChromaDB", "FAIL", str(exc))
    return DiagnosticCheck("ChromaDB", "PASS", str(path))


def _check_neo4j(settings: Settings) -> DiagnosticCheck:
    if not settings.neo4j_uri:
        return DiagnosticCheck("Neo4j", "WARN", "NEO4J_URI is not configured.")
    graph_store = Neo4jGraphStore(settings)
    available, message = graph_store.check_connection()
    graph_store.close()
    status = "PASS" if available else "WARN"
    return DiagnosticCheck("Neo4j", status, message)


def _check_fastapi_app_import() -> DiagnosticCheck:
    try:
        importlib.import_module("multi_agentic_rag.api.main")
    except Exception as exc:
        return DiagnosticCheck("FastAPI app", "FAIL", str(exc))
    return DiagnosticCheck("FastAPI app", "PASS", "multi_agentic_rag.api.main imports.")
