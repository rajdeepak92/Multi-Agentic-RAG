"""Runtime diagnostics shared by CLI and FastAPI."""

from __future__ import annotations

import importlib
import socket
import sys
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.llm import select_llm_client
from multi_agentic_rag.retrieval.reranker import BGEReranker, select_reranker
from multi_agentic_rag.simulators import check_rest_mqtt_simulators
from multi_agentic_rag.storage.embedding_factory import select_embedding_function
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore
from multi_agentic_rag.storage.registry import select_registry
from multi_agentic_rag.storage.vector_factory import select_vector_store
from multi_agentic_rag.storage.weaviate_store import WeaviateVectorStore
from multi_agentic_rag.utils.paths import resolve_path


@dataclass(frozen=True)
class DiagnosticCheck:
    """One doctor check result."""

    name: str
    status: str
    detail: str


def run_diagnostics(
    settings: Settings | None = None,
    *,
    target_graphrag: bool = False,
    system_name: str | None = None,
    version: str | None = None,
) -> list[DiagnosticCheck]:
    """Run local environment checks and optional target-mode checks."""

    settings = settings or get_settings()
    checks = [
        _check_python_version(),
        _check_dotenv(),
        _check_openai_key(settings),
        _check_embedding_provider(settings),
        _check_hf_token(settings),
        _check_registry(settings),
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
    if target_graphrag:
        checks.extend(_target_graphrag_checks(settings, system_name=system_name, version=version))
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
    if settings.llm_provider == "openai":
        return DiagnosticCheck("OPENAI_API_KEY", "WARN", "Missing. Required for OpenAI routing.")
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


def _check_registry(settings: Settings) -> DiagnosticCheck:
    try:
        selection = select_registry(settings)
        selection.registry.initialize()
    except Exception as exc:
        return DiagnosticCheck("Registry", "FAIL", str(exc))
    if selection.provider == "sqlite":
        return DiagnosticCheck("Registry", "PASS", str(resolve_path(settings.sqlite_db_path)))
    return DiagnosticCheck("Registry", "PASS", "PostgreSQL registry initialized.")


def _check_keyword_index(settings: Settings) -> DiagnosticCheck:
    if not settings.keyword_index_enabled:
        return DiagnosticCheck("Keyword index", "WARN", "Disabled by settings.")
    try:
        registry = select_registry(settings).registry
        registry.initialize()
        registry.search_chunks("doctor", top_k=1)
    except Exception as exc:
        return DiagnosticCheck("Keyword index", "WARN", str(exc))
    return DiagnosticCheck("Keyword index", "PASS", "Ready.")


def _check_object_store(settings: Settings) -> DiagnosticCheck:
    try:
        path = resolve_path(settings.object_store_path)
        path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return DiagnosticCheck("Local object store", "FAIL", str(exc))
    return DiagnosticCheck("Local object store", "PASS", str(path))


def _check_chroma(settings: Settings) -> DiagnosticCheck:
    if settings.vector_store_provider == "weaviate" and not settings.allow_local_dev_mode:
        return DiagnosticCheck("ChromaDB", "PASS", "Weaviate selected; Chroma is not required.")
    try:
        path = resolve_path(settings.chroma_path)
        path.mkdir(parents=True, exist_ok=True)
        importlib.import_module("chromadb")
    except ModuleNotFoundError:
        return DiagnosticCheck("ChromaDB", "WARN", "chromadb is not installed.")
    except Exception as exc:
        return DiagnosticCheck("ChromaDB", "FAIL", str(exc))
    return DiagnosticCheck("ChromaDB", "PASS", f"Configured local Chroma store at {path}")


def _check_weaviate(settings: Settings) -> DiagnosticCheck:
    if settings.vector_store_provider == "chroma":
        if not settings.allow_local_dev_mode:
            return DiagnosticCheck(
                "Weaviate",
                "FAIL",
                "VECTOR_STORE_PROVIDER=chroma requires ALLOW_LOCAL_DEV_MODE=true.",
            )
        return DiagnosticCheck(
            "Weaviate",
            "PASS",
            "Chroma provider selected; Weaviate is not required for local ingestion.",
        )
    if not settings.weaviate_url:
        status = "WARN" if settings.allow_local_dev_mode else "FAIL"
        return DiagnosticCheck("Weaviate", status, "WEAVIATE_URL is required for strict mode.")
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
    if not settings.allow_local_dev_mode and not _neo4j_uri_is_local(settings.neo4j_uri):
        return DiagnosticCheck(
            "Neo4j Desktop config",
            "PASS",
            "Managed/remote Neo4j expected; Desktop config is not required.",
        )
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
    if not _neo4j_uri_is_local(settings.neo4j_uri):
        return DiagnosticCheck(
            "Neo4j ports",
            "PASS",
            "Managed/remote Neo4j URI; local port probe skipped.",
        )
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


def _neo4j_uri_is_local(uri: str | None) -> bool:
    if not uri:
        return True
    normalized = uri.lower()
    return any(host in normalized for host in ("localhost", "127.0.0.1", "0.0.0.0"))


def _check_fastapi_app_import() -> DiagnosticCheck:
    try:
        importlib.import_module("multi_agentic_rag.api.main")
    except Exception as exc:
        return DiagnosticCheck("FastAPI app", "FAIL", str(exc))
    return DiagnosticCheck("FastAPI app", "PASS", "multi_agentic_rag.api.main imports.")


def _target_graphrag_checks(
    settings: Settings,
    *,
    system_name: str | None,
    version: str | None,
) -> list[DiagnosticCheck]:
    checks = [
        _require_target_setting(
            "Target mode",
            settings.marag_target_mode == "target-graphrag",
            "Set MARAG_TARGET_MODE=target-graphrag.",
        ),
        _require_target_setting(
            "Target registry",
            settings.registry_provider == "postgresql" and bool(settings.postgres_dsn),
            "Target mode requires REGISTRY_PROVIDER=postgresql and POSTGRES_DSN.",
        ),
        _require_target_setting(
            "Target vector store",
            settings.vector_store_provider == "weaviate" and bool(settings.weaviate_url),
            "Target mode requires VECTOR_STORE_PROVIDER=weaviate and WEAVIATE_URL.",
        ),
        _require_target_setting(
            "Target embeddings",
            settings.embedding_provider == "huggingface"
            and settings.default_embedding_model == "BAAI/bge-m3",
            "Target mode requires EMBEDDING_PROVIDER=huggingface and DEFAULT_EMBEDDING_MODEL=BAAI/bge-m3.",
        ),
        _check_target_reranker(settings),
        _check_target_llm(settings),
        _check_target_simulators(settings),
    ]
    checks.append(_check_target_graph_population(settings, system_name=system_name, version=version))
    return checks


def _require_target_setting(name: str, ok: bool, detail: str) -> DiagnosticCheck:
    return DiagnosticCheck(name, "PASS" if ok else "FAIL", "Configured." if ok else detail)


def _check_target_reranker(settings: Settings) -> DiagnosticCheck:
    try:
        selection = select_reranker(settings)
    except Exception as exc:
        return DiagnosticCheck("Target reranker", "FAIL", str(exc))
    if selection.provider != "huggingface" or selection.model_name != "BAAI/bge-reranker-v2-m3":
        return DiagnosticCheck(
            "Target reranker",
            "FAIL",
            "Target mode requires RERANKER_PROVIDER=huggingface and DEFAULT_RERANKER_MODEL=BAAI/bge-reranker-v2-m3.",
        )
    reranker = selection.reranker
    if isinstance(reranker, BGEReranker):
        ready, message = reranker.check_ready(load_model=False)
        return DiagnosticCheck("Target reranker", "PASS" if ready else "FAIL", message)
    return DiagnosticCheck("Target reranker", "FAIL", "BGE reranker was not selected.")


def _check_target_llm(settings: Settings) -> DiagnosticCheck:
    if settings.llm_provider != "openai":
        return DiagnosticCheck("Target LLM", "FAIL", "Target mode requires LLM_PROVIDER=openai.")
    ready, message = select_llm_client(settings).check_ready()
    return DiagnosticCheck("Target LLM", "PASS" if ready else "FAIL", message)


def _check_target_simulators(settings: Settings) -> DiagnosticCheck:
    readiness = check_rest_mqtt_simulators(settings)
    if readiness.ready:
        return DiagnosticCheck("Target REST/MQTT simulators", "PASS", "Configured.")
    return DiagnosticCheck("Target REST/MQTT simulators", "FAIL", "; ".join(readiness.missing))


def _check_target_graph_population(
    settings: Settings,
    *,
    system_name: str | None,
    version: str | None,
) -> DiagnosticCheck:
    _ = version
    if not system_name:
        return DiagnosticCheck(
            "Target graph population",
            "FAIL",
            "Pass --system to validate graph population for a specific system.",
        )
    try:
        from multi_agentic_rag.retrieval.graph_retriever import GraphRetriever

        result = GraphRetriever(settings).get_lineage(system_name)
    except Exception as exc:
        return DiagnosticCheck("Target graph population", "FAIL", str(exc))
    if result.warning:
        return DiagnosticCheck("Target graph population", "FAIL", result.warning)
    if not result.records:
        return DiagnosticCheck(
            "Target graph population",
            "FAIL",
            f"No graph lineage records found for {system_name}.",
        )
    return DiagnosticCheck(
        "Target graph population",
        "PASS",
        f"{len(result.records)} lineage record(s) found for {system_name}.",
    )
