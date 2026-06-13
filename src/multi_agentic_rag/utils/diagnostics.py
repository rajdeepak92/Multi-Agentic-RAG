"""Runtime diagnostics shared by CLI and FastAPI."""

from __future__ import annotations

import importlib
import socket
import sys
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.storage.embedding_factory import select_embedding_function
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.storage.vector_factory import select_vector_store
from multi_agentic_rag.storage.weaviate_store import WeaviateVectorStore
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
        _check_embedding_provider(settings),
        _check_hf_token(settings),
        _check_sqlite(settings),
        _check_keyword_index(settings),
        _check_object_store(settings),
        _check_chroma(settings),
        _check_weaviate(settings),
        _check_vector_selection(settings),
        _check_pdf_parsers(settings),
        _check_neo4j_desktop_config(settings),
        _check_neo4j_ports(settings),
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
    if settings.llm_provider == "none":
        return DiagnosticCheck(
            "OPENAI_API_KEY",
            "PASS",
            "LLM provider is disabled; key is not required.",
        )
    if settings.openai_api_key:
        return DiagnosticCheck("OPENAI_API_KEY", "PASS", "Configured.")
    return DiagnosticCheck(
        "OPENAI_API_KEY",
        "WARN",
        "Missing. Required only for future LLM-backed generation.",
    )


def _check_hf_token(settings: Settings) -> DiagnosticCheck:
    if settings.embedding_provider == "hash":
        return DiagnosticCheck(
            "HF_TOKEN",
            "PASS",
            "Hash embeddings selected; token is not required.",
        )
    if settings.hf_token:
        return DiagnosticCheck("HF_TOKEN", "PASS", "Configured.")
    return DiagnosticCheck("HF_TOKEN", "WARN", "Missing. Public Hugging Face models may still work.")


def _check_embedding_provider(settings: Settings) -> DiagnosticCheck:
    try:
        selection = select_embedding_function(settings)
    except Exception as exc:
        return DiagnosticCheck("Embedding provider", "FAIL", str(exc))
    if selection.provider == "hash":
        return DiagnosticCheck(
            "Embedding provider",
            "WARN",
            "Hash embeddings selected; use only for deterministic tests/offline validation.",
        )
    try:
        importlib.import_module("sentence_transformers")
    except ModuleNotFoundError:
        return DiagnosticCheck(
            "Embedding provider",
            "FAIL",
            "sentence-transformers is required for EMBEDDING_PROVIDER=huggingface.",
        )
    return DiagnosticCheck(
        "Embedding provider",
        "PASS",
        f"{selection.provider}: {selection.model_name}",
    )


def _check_sqlite(settings: Settings) -> DiagnosticCheck:
    try:
        registry = SQLiteRegistry(settings.sqlite_db_path)
        registry.initialize()
    except Exception as exc:
        return DiagnosticCheck("SQLite registry", "FAIL", str(exc))
    return DiagnosticCheck("SQLite registry", "PASS", str(resolve_path(settings.sqlite_db_path)))


def _check_keyword_index(settings: Settings) -> DiagnosticCheck:
    if not settings.keyword_index_enabled:
        return DiagnosticCheck("SQLite FTS5 keyword index", "WARN", "Disabled by settings.")
    try:
        registry = SQLiteRegistry(settings.sqlite_db_path)
        registry.initialize()
        registry.search_chunks("doctor", top_k=1)
    except Exception as exc:
        return DiagnosticCheck("SQLite FTS5 keyword index", "WARN", str(exc))
    return DiagnosticCheck("SQLite FTS5 keyword index", "PASS", "Ready.")


def _check_object_store(settings: Settings) -> DiagnosticCheck:
    try:
        path = resolve_path(settings.object_store_path)
        path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return DiagnosticCheck("Local object store", "FAIL", str(exc))
    return DiagnosticCheck("Local object store", "PASS", str(path))


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


def _check_weaviate(settings: Settings) -> DiagnosticCheck:
    if settings.vector_store_provider == "chroma":
        return DiagnosticCheck(
            "Weaviate",
            "PASS",
            "Chroma provider selected; Weaviate is not required.",
        )
    if not settings.weaviate_url:
        return DiagnosticCheck("Weaviate", "PASS", "WEAVIATE_URL not set; Chroma fallback is used.")
    store = WeaviateVectorStore(
        url=settings.weaviate_url,
        api_key=settings.weaviate_api_key,
        collection_name=settings.weaviate_collection,
        hybrid_alpha=settings.weaviate_hybrid_alpha,
    )
    available, message = store.check_connection()
    status = "PASS" if available else "WARN"
    return DiagnosticCheck("Weaviate", status, message)


def _check_vector_selection(settings: Settings) -> DiagnosticCheck:
    try:
        selection = select_vector_store(settings)
    except Exception as exc:
        return DiagnosticCheck("Vector provider", "FAIL", str(exc))
    return DiagnosticCheck("Vector provider", "PASS", f"{selection.provider}: {selection.reason}")


def _check_pdf_parsers(settings: Settings) -> DiagnosticCheck:
    parser_names = []
    missing = []
    for module_name, display_name, required in (
        ("fitz", "PyMuPDF", True),
        ("pdfplumber", "pdfplumber", False),
        ("docx", "python-docx", True),
        ("pytesseract", "pytesseract", settings.enable_pdf_ocr),
        ("PIL", "Pillow", settings.enable_pdf_ocr),
    ):
        try:
            importlib.import_module(module_name)
            parser_names.append(display_name)
        except ModuleNotFoundError:
            if required:
                missing.append(display_name)
    if missing:
        return DiagnosticCheck("PDF parsers", "FAIL", f"Missing: {', '.join(missing)}")
    return DiagnosticCheck("PDF parsers", "PASS", ", ".join(parser_names))


def _check_neo4j_desktop_config(settings: Settings) -> DiagnosticCheck:
    missing = []
    for name, path in (
        ("NEO4J_DBMS_HOME", settings.neo4j_dbms_home),
        ("NEO4J_JAVA_HOME", settings.neo4j_java_home),
    ):
        if not path:
            missing.append(name)
        elif not resolve_path(path).exists():
            missing.append(f"{name} missing at {resolve_path(path)}")
    if missing:
        return DiagnosticCheck(
            "Neo4j Desktop config",
            "WARN",
            "; ".join(missing),
        )
    return DiagnosticCheck("Neo4j Desktop config", "PASS", "Startup script paths are configured.")


def _check_neo4j_ports(settings: Settings) -> DiagnosticCheck:
    checks = (
        ("Bolt", settings.neo4j_bolt_port),
        ("Browser", settings.neo4j_browser_port),
    )
    unavailable = [
        f"{name} {settings.neo4j_host}:{port}"
        for name, port in checks
        if not _tcp_port_open(settings.neo4j_host, port)
    ]
    if unavailable:
        return DiagnosticCheck(
            "Neo4j ports",
            "FAIL" if settings.graphrag_required else "WARN",
            "Not listening: " + ", ".join(unavailable),
        )
    return DiagnosticCheck(
        "Neo4j ports",
        "PASS",
        f"{settings.neo4j_host}:{settings.neo4j_bolt_port}, "
        f"{settings.neo4j_host}:{settings.neo4j_browser_port}",
    )


def _check_neo4j(settings: Settings) -> DiagnosticCheck:
    if not settings.neo4j_uri:
        status = "FAIL" if settings.graphrag_required else "WARN"
        return DiagnosticCheck("Neo4j", status, "NEO4J_URI is not configured.")
    graph_store = Neo4jGraphStore(settings)
    available, message = graph_store.check_connection()
    graph_store.close()
    status = "PASS" if available else ("FAIL" if settings.graphrag_required else "WARN")
    return DiagnosticCheck("Neo4j", status, message)


def _tcp_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _check_fastapi_app_import() -> DiagnosticCheck:
    try:
        importlib.import_module("multi_agentic_rag.api.main")
    except Exception as exc:
        return DiagnosticCheck("FastAPI app", "FAIL", str(exc))
    return DiagnosticCheck("FastAPI app", "PASS", "multi_agentic_rag.api.main imports.")
