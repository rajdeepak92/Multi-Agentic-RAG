"""Typer command-line interface for the GraphRAG-only runtime."""

from __future__ import annotations

import asyncio
import gc
import os
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from multi_agentic_rag.agents import (
    AgentIngestDocument,
    AgentRetrieveAnswer,
    AgentUserStoryBuilder,
    FlowValidatorAgent,
    IntentRouterAgent,
    KnowledgeBaseStoringAgent,
    LangGraphWorkflowRunner,
    WorkflowPlannerAgent,
)
from multi_agentic_rag.app import build_application
from multi_agentic_rag.config import Settings, get_settings, reload_settings
from multi_agentic_rag.domain import TaskIntent, TaskIntentType
from multi_agentic_rag.exceptions import MultiAgenticRagError
from multi_agentic_rag.infrastructure.chroma import ChromaVectorRepository
from multi_agentic_rag.infrastructure.neo4j import Neo4jGraphRepository
from multi_agentic_rag.infrastructure.postgres import PostgresKnowledgeRepository
from multi_agentic_rag.llm import (
    HF_REASONING_GPU_INSTALL_HINT,
    HFReasoningEnvironmentReport,
    HuggingFaceReasoningClient,
    ReasoningClient,
    ReasoningModelSelector,
    build_reasoning_client,
    format_hf_reasoning_preflight_error,
    inspect_hf_reasoning_environment,
)
from multi_agentic_rag.retrieval import (
    BM25Retriever,
    GraphRetriever,
    HybridKnowledgeRetriever,
    VectorRetriever,
    build_lexical_repository,
)
from multi_agentic_rag.retrieval.reranker import select_reranker
from multi_agentic_rag.runtime import (
    apply_project_config,
    resolve_project_root,
)
from multi_agentic_rag.runtime.secrets import redact_secrets

app = typer.Typer(
    name="multi-agentic-rag",
    help="GraphRAG-only knowledge base ingestion and retrieval.",
    no_args_is_help=True,
)
console = Console()
SUPPORTED_DOCUMENT_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".markdown"}
MODEL_OPTION_HELP = (
    "Compatibility reasoning-provider override. Normal commands use "
    "base_config.json -> reasoning.provider."
)
REVIEW_FACTS_OPTION_HELP = (
    "Run LLM fact review during ingestion. Defaults off so ingest stays deterministic "
    "and does not invoke local HF generation per chunk."
)
OPENAI_QUOTA_HINT = (
    "OpenAI quota is exhausted. Rerun the same command with `--model hf` after installing "
    "`uv sync --dev --extra hf-reasoning --extra cpu --link-mode=copy` for CPU or "
    "`uv sync --dev --extra hf-reasoning --extra gpu --link-mode=copy` for NVIDIA GPU, "
    "then use `uv run --no-sync`."
)


@app.callback()
def bootstrap_project_cache(
    debug: Annotated[bool, typer.Option("--debug", help="Show debug logs.")] = False,
) -> None:
    """Create project-local cache directories before command execution."""

    try:
        resolved_root = resolve_project_root(require=False)
        if resolved_root is not None:
            apply_project_config(
                resolved_root,
                cli_overrides={
                    "debug": debug,
                },
            )
            reload_settings()
        settings = get_settings()
        if debug:
            settings.log_level = "DEBUG"
        settings.ensure_project_cache_paths()
    except MultiAgenticRagError as exc:
        _print_cli_error(exc)


@app.command("ingest")
def ingest(
    document_path: Annotated[Path, typer.Argument(help="Path to PDF, DOCX, TXT, or Markdown.")],
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str, typer.Option("--version", help="Document version.")],
    kb: Annotated[str, typer.Option("--kb", help="Knowledge base name or context.")] = "default",
    model: Annotated[
        ReasoningModelSelector | None,
        typer.Option("--model", help=MODEL_OPTION_HELP),
    ] = None,
    review_facts: Annotated[
        bool,
        typer.Option("--review-facts/--no-review-facts", help=REVIEW_FACTS_OPTION_HELP),
    ] = False,
) -> None:
    """Ingest a versioned document into PostgreSQL, Chroma, and Neo4j.

    Args:
        document_path: Local source file to ingest. Supported extensions are
            PDF, DOCX, TXT, Markdown, and related text-like formats.
        system: Logical system name used to scope lineage, retrieval, and graph
            projection.
        version: Source document version. This is validated against the file
            name when the name exposes a version token.
        kb: Knowledge-base name or context under the selected system.
        model: Reasoning backend for optional ingest-time fact review.
        review_facts: Whether to run LLM review over extracted facts.
    """

    try:
        settings = get_settings()
        result = asyncio.run(
            _build_ingestion_agent(
                model,
                settings=settings,
                review_facts=review_facts,
            ).ingest(
                document_path,
                kb,
                system=system,
                version=version,
            )
        )
    except MultiAgenticRagError as exc:
        _print_cli_error(exc)
    _print_ingest_result(result.model_dump())


@app.command("ingest-directory")
def ingest_directory(
    directory_path: Annotated[Path, typer.Argument(help="Directory containing source documents.")],
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str, typer.Option("--version", help="Document version.")],
    kb: Annotated[str, typer.Option("--kb", help="Knowledge base name or context.")] = "default",
    recursive: Annotated[
        bool,
        typer.Option("--recursive/--no-recursive", help="Search subdirectories."),
    ] = True,
    model: Annotated[
        ReasoningModelSelector | None,
        typer.Option("--model", help=MODEL_OPTION_HELP),
    ] = None,
    review_facts: Annotated[
        bool,
        typer.Option("--review-facts/--no-review-facts", help=REVIEW_FACTS_OPTION_HELP),
    ] = False,
) -> None:
    """Ingest every supported document in a directory.

    Args:
        directory_path: Directory containing PDF, DOCX, TXT, Markdown, or
            `.markdown` files.
        system: Logical system name used to scope lineage, retrieval, and graph
            projection.
        version: Source document version to apply to every file in the batch.
        kb: Knowledge-base name or context under the selected system.
        recursive: Whether to scan nested directories.
        model: Reasoning backend for optional ingest-time fact review.
        review_facts: Whether to run LLM review over extracted facts.
    """

    files = _document_files(directory_path, recursive=recursive)
    if not files:
        console.print("[yellow]No supported documents found.[/yellow]")
        raise typer.Exit(code=1)
    results = asyncio.run(
        _ingest_many(
            files,
            system=system,
            version=version,
            kb=kb,
            model=model,
            review_facts=review_facts,
        )
    )
    table = Table(title="Directory Ingestion")
    table.add_column("Document")
    table.add_column("Status")
    table.add_column("Document Version ID")
    table.add_column("Chunks")
    table.add_column("Facts")
    table.add_column("Warnings")
    failures = 0
    for path, result, error in results:
        if error:
            failures += 1
            table.add_row(path.name, "[red]FAIL[/red]", "-", "-", "-", error)
            continue
        assert result is not None
        table.add_row(
            path.name,
            "[green]PASS[/green]",
            str(result["document_version_id"]),
            str(result["chunks_count"]),
            str(result["facts_count"]),
            "; ".join(result["warnings"]),
        )
    console.print(table)
    if failures:
        for _, _, error in results:
            if error and _quota_hint_for_message(error):
                console.print(f"[yellow]HINT[/yellow] {_quota_hint_for_message(error)}")
                break
        raise typer.Exit(code=1)


@app.command("clean-system-state")
def clean_system_state(
    system: Annotated[
        str | None,
        typer.Option("--system", help="System name to clean. Omit only with --all."),
    ] = None,
    kb: Annotated[
        str | None,
        typer.Option("--kb", help="Optional knowledge-base scope inside --system."),
    ] = None,
    all_data: Annotated[
        bool,
        typer.Option("--all", help="Delete all GraphRAG rows, vectors, and graph nodes."),
    ] = False,
    delete_cache: Annotated[
        bool,
        typer.Option("--delete-cache", help="Delete runtime/cache directories; requires --all."),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm destructive cleanup.")] = False,
) -> None:
    """Clean PostgreSQL, ChromaDB, and Neo4j state.

    Args:
        system: Optional system scope. Required unless `--all` is supplied.
        kb: Optional knowledge-base scope within the selected system.
        all_data: Delete all GraphRAG data from every configured backend.
        delete_cache: Delete `.global_cache`, legacy runtime paths, and `.cache` after database
            cleanup. This is intentionally all-or-nothing.
        yes: Required confirmation flag for non-interactive runs.
    """

    scope_system, scope_kb = _resolve_cleanup_scope(
        system=system,
        kb=kb,
        all_data=all_data,
    )
    if delete_cache and not all_data:
        console.print("[red]FAIL[/red] --delete-cache requires --all.")
        raise typer.Exit(code=1)
    _confirm_cleanup(yes, "Delete configured GraphRAG state?")

    settings = get_settings()
    postgres_counts = asyncio.run(_clear_postgres_state(settings, scope_system, scope_kb))
    chroma_deleted = _clear_chroma_state(settings, scope_system, scope_kb)
    graph_deleted = _clear_neo4j_state(settings, scope_system, scope_kb)
    deleted_paths, skipped_paths = _delete_runtime_cache(settings) if delete_cache else ([], [])

    _print_cleanup_table(
        "Clean System State",
        [
            ("PostgreSQL rows", sum(postgres_counts.values())),
            ("Chroma vectors", chroma_deleted),
            ("Neo4j nodes", graph_deleted),
            ("Runtime/cache paths", len(deleted_paths)),
        ],
    )
    if deleted_paths:
        for path in deleted_paths:
            console.print(f"deleted_path: {path}")
    if skipped_paths:
        for path, reason in skipped_paths:
            console.print(f"[yellow]WARN[/yellow] could_not_delete: {path} ({reason})")
        raise typer.Exit(code=1)


@app.command("clean-postgres-state")
def clean_postgres_state(
    system: Annotated[
        str | None,
        typer.Option("--system", help="System name to clean. Omit only with --all."),
    ] = None,
    kb: Annotated[
        str | None,
        typer.Option("--kb", help="Optional knowledge-base scope inside --system."),
    ] = None,
    all_data: Annotated[
        bool,
        typer.Option("--all", help="Delete all PostgreSQL GraphRAG rows."),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm destructive cleanup.")] = False,
) -> None:
    """Clean PostgreSQL state only."""

    scope_system, scope_kb = _resolve_cleanup_scope(
        system=system,
        kb=kb,
        all_data=all_data,
    )
    _confirm_cleanup(yes, "Delete configured PostgreSQL state?")
    counts = asyncio.run(_clear_postgres_state(get_settings(), scope_system, scope_kb))
    _print_cleanup_table("Clean PostgreSQL State", [("PostgreSQL rows", sum(counts.values()))])


@app.command("clean-chroma-state")
def clean_chroma_state(
    system: Annotated[
        str | None,
        typer.Option("--system", help="System name to clean. Omit only with --all."),
    ] = None,
    kb: Annotated[
        str | None,
        typer.Option("--kb", help="Optional knowledge-base scope inside --system."),
    ] = None,
    all_data: Annotated[
        bool,
        typer.Option("--all", help="Delete all vectors in the configured Chroma collection."),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm destructive cleanup.")] = False,
) -> None:
    """Clean Chroma vector state only."""

    scope_system, scope_kb = _resolve_cleanup_scope(
        system=system,
        kb=kb,
        all_data=all_data,
    )
    _confirm_cleanup(yes, "Delete configured Chroma state?")
    deleted = _clear_chroma_state(get_settings(), scope_system, scope_kb)
    _print_cleanup_table("Clean Chroma State", [("Chroma vectors", deleted)])


@app.command("clean-neo4j-state")
def clean_neo4j_state(
    system: Annotated[
        str | None,
        typer.Option("--system", help="System name to clean. Omit only with --all."),
    ] = None,
    kb: Annotated[
        str | None,
        typer.Option("--kb", help="Optional knowledge-base scope inside --system."),
    ] = None,
    all_data: Annotated[
        bool,
        typer.Option("--all", help="Delete all graph nodes in the configured Neo4j database."),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm destructive cleanup.")] = False,
) -> None:
    """Clean Neo4j graph state only."""

    scope_system, scope_kb = _resolve_cleanup_scope(
        system=system,
        kb=kb,
        all_data=all_data,
    )
    _confirm_cleanup(yes, "Delete configured Neo4j state?")
    deleted = _clear_neo4j_state(get_settings(), scope_system, scope_kb)
    _print_cleanup_table("Clean Neo4j State", [("Neo4j nodes", deleted)])


def _resolve_cleanup_scope(
    *,
    system: str | None,
    kb: str | None,
    all_data: bool,
) -> tuple[str | None, str | None]:
    if all_data and system:
        console.print("[red]FAIL[/red] Use either --all or --system, not both.")
        raise typer.Exit(code=1)
    if not all_data and not system:
        console.print("[red]FAIL[/red] Provide --system or --all.")
        raise typer.Exit(code=1)
    if all_data and kb:
        console.print("[red]FAIL[/red] --kb can only be used with --system.")
        raise typer.Exit(code=1)
    return (None, None) if all_data else (system, kb)


def _confirm_cleanup(yes: bool, prompt: str) -> None:
    if not yes and not typer.confirm(prompt):
        raise typer.Exit(code=1)


async def _clear_postgres_state(
    settings: Settings,
    system_name: str | None,
    kb_name: str | None,
) -> dict[str, int]:
    return await PostgresKnowledgeRepository.from_settings(settings).clear(
        system_name=system_name,
        kb_name=kb_name,
    )


def _clear_chroma_state(
    settings: Settings,
    system_name: str | None,
    kb_name: str | None,
) -> int:
    chroma_repo = ChromaVectorRepository.from_settings(settings)
    try:
        return chroma_repo.clear(
            system_name=system_name,
            kb_name=kb_name,
        )
    finally:
        chroma_repo.close()
        del chroma_repo
        gc.collect()


def _clear_neo4j_state(
    settings: Settings,
    system_name: str | None,
    kb_name: str | None,
) -> int:
    graph_repo = Neo4jGraphRepository(settings)
    try:
        graph_ready, graph_message = graph_repo.check_connection()
        if not graph_ready:
            console.print(f"[red]FAIL[/red] Neo4j cleanup unavailable: {graph_message}")
            raise typer.Exit(code=1)
        return graph_repo.clear(system_name=system_name, kb_name=kb_name)
    finally:
        graph_repo.close()
        gc.collect()


def _print_cleanup_table(title: str, rows: list[tuple[str, int]]) -> None:
    table = Table(title=title)
    table.add_column("Target")
    table.add_column("Deleted")
    for target, deleted in rows:
        table.add_row(target, str(deleted))
    console.print(table)


def _print_ingest_result(rows: dict[str, Any]) -> None:
    for key in (
        "document_id",
        "document_version_id",
        "chunks_count",
        "facts_count",
        "deltas_count",
        "postgres_status",
        "chroma_status",
        "neo4j_status",
        "bm25_status",
        "ingestion_run_id",
    ):
        console.print(f"{key}: {rows[key]}")
    for warning in rows["warnings"]:
        console.print(f"[yellow]WARN[/yellow] {warning}")


@app.command("retrieve")
def retrieve(
    query: Annotated[str, typer.Argument(help="Query text.")],
    system: Annotated[str, typer.Option("--system", help="System name.")],
    kb: Annotated[str, typer.Option("--kb", help="Knowledge base name or context.")] = "default",
    version: Annotated[str | None, typer.Option("--version", help="Optional version.")] = None,
    top_k: Annotated[int, typer.Option("--top-k", help="Number of chunks to return.")] = 5,
    show_graph_paths: Annotated[
        bool,
        typer.Option("--show-graph-paths", help="Print graph traversal paths for graph hits."),
    ] = False,
) -> None:
    """Retrieve ranked evidence chunks.

    Args:
        query: Natural-language query or keyword phrase to match against the
            knowledge base.
        system: Logical system name that constrains the retrieval search.
        kb: Knowledge-base name or context under the selected system.
        version: Optional document version filter. When omitted, retrieval uses
            active chunks for the knowledge base.
        top_k: Maximum number of evidence chunks to print.
        show_graph_paths: Whether to print graph traversal reasons and paths.
    """

    try:
        results = asyncio.run(
            _build_retriever().retrieve(
                query,
                system_name=system,
                kb_name=kb,
                version=version,
                top_k=top_k,
            )
        )
    except MultiAgenticRagError as exc:
        console.print(f"[red]FAIL[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if not results:
        console.print("[yellow]No evidence found.[/yellow]")
        return
    table = Table(title="Retrieval Results")
    table.add_column("Score")
    table.add_column("Version")
    table.add_column("Source")
    table.add_column("Page")
    table.add_column("Signals")
    table.add_column("Text")
    for result in results:
        table.add_row(
            f"{result.score:.4f}",
            result.version,
            result.source_name,
            str(result.page),
            ",".join(result.sources),
            result.text[:180].replace("\n", " "),
        )
    console.print(table)
    if show_graph_paths:
        _print_graph_paths(results)


@app.command("ask")
def ask(
    question: Annotated[str, typer.Argument(help="Question to answer from project evidence.")],
    system: Annotated[str, typer.Option("--system", help="System name.")],
    kb: Annotated[str, typer.Option("--kb", help="Knowledge base name or context.")] = "default",
    version: Annotated[str | None, typer.Option("--version", help="Optional version.")] = None,
    model: Annotated[
        ReasoningModelSelector | None,
        typer.Option("--model", help=MODEL_OPTION_HELP),
    ] = None,
) -> None:
    """Answer a question using validated hybrid evidence and model synthesis."""

    intent = TaskIntent(
        intent_type=TaskIntentType.ANSWER_QUERY,
        system=system,
        kb=kb,
        version=version,
        confidence=1.0,
    )
    result = asyncio.run(_build_answer_agent(model).run(intent, question=question))
    if result.status.value in {"failed", "blocked"}:
        _print_agent_failure(result.messages)
    for message in result.messages:
        console.print(message)


@app.command("user-stories")
def user_stories(
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str, typer.Option("--version", help="Document version.")],
    kb: Annotated[str, typer.Option("--kb", help="Knowledge base name or context.")] = "default",
    model: Annotated[
        ReasoningModelSelector | None,
        typer.Option("--model", help=MODEL_OPTION_HELP),
    ] = None,
) -> None:
    """Generate user-story YAML artifacts from an already ingested version."""

    intent = TaskIntent(
        intent_type=TaskIntentType.BUILD_USER_STORIES,
        system=system,
        kb=kb,
        version=version,
        confidence=1.0,
    )
    result = asyncio.run(_build_user_story_agent(model).run(intent))
    if result.status.value != "succeeded":
        _print_agent_failure(result.messages)
    for path in result.artifact_paths:
        console.print(f"artifact: {path}")


@app.command("ingest-and-user-stories")
def ingest_and_user_stories(
    document_path: Annotated[Path, typer.Argument(help="Path to PDF, DOCX, TXT, or Markdown.")],
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str, typer.Option("--version", help="Document version.")],
    kb: Annotated[str, typer.Option("--kb", help="Knowledge base name or context.")] = "default",
    model: Annotated[
        ReasoningModelSelector | None,
        typer.Option("--model", help=MODEL_OPTION_HELP),
    ] = None,
    review_facts: Annotated[
        bool,
        typer.Option("--review-facts/--no-review-facts", help=REVIEW_FACTS_OPTION_HELP),
    ] = False,
) -> None:
    """Ingest one document and then generate user-story artifacts."""

    try:
        application = build_application(
            settings=get_settings(),
            model_selector=model,
            review_facts=review_facts,
        )
        ingest_result, story_result = asyncio.run(
            application.ingest_then_user_stories(
                document_path=document_path,
                system=system,
                version=version,
                kb=kb,
            )
        )
    except MultiAgenticRagError as exc:
        _print_cli_error(exc)
    if ingest_result.ingest_result is not None:
        console.print(f"ingested: {ingest_result.ingest_result.document_version_id}")
    for warning in ingest_result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")
    for path in story_result.artifact_paths:
        console.print(f"artifact: {path}")


@app.command("run")
def run_task(
    task: Annotated[str, typer.Argument(help="Natural-language task to route.")],
    system: Annotated[
        str | None,
        typer.Option("--system", help="Optional system name default."),
    ] = None,
    kb: Annotated[str, typer.Option("--kb", help="Knowledge base name or context.")] = "default",
    version: Annotated[
        str | None,
        typer.Option("--version", help="Optional document version default."),
    ] = None,
    document: Annotated[
        Path | None,
        typer.Option("--document", help="Optional document path default."),
    ] = None,
    model: Annotated[
        ReasoningModelSelector | None,
        typer.Option("--model", help=MODEL_OPTION_HELP),
    ] = None,
    review_facts: Annotated[
        bool,
        typer.Option("--review-facts/--no-review-facts", help=REVIEW_FACTS_OPTION_HELP),
    ] = False,
) -> None:
    """Route a natural-language task through the LangGraph workflow."""

    documents = [str(document)] if document else []
    state = asyncio.run(
        _build_workflow_runner(model, review_facts=review_facts).run(
            task,
            system=system,
            kb=kb,
            version=version,
            documents=documents,
        )
    )
    if state.status.value in {"failed", "blocked"}:
        final_response = state.final_response or "Workflow failed."
        console.print(f"[red]FAIL[/red] {final_response}")
        if hint := _quota_hint_for_message(final_response):
            console.print(f"[yellow]HINT[/yellow] {hint}")
        raise typer.Exit(code=1)
    console.print(state.final_response or "Workflow completed.")


@app.command("db-check")
def db_check() -> None:
    """Check PostgreSQL, configured lexical backend, and migration readiness."""

    settings = get_settings()
    repository = PostgresKnowledgeRepository.from_settings(settings)
    readiness = asyncio.run(repository.check_lexical_readiness())
    alembic_ready, alembic_detail = _alembic_revision_status(settings.postgres_dsn)
    status = readiness.ready and alembic_ready
    detail = f"{readiness.detail}; Alembic {alembic_detail}"
    _print_check("PostgreSQL", status, detail)


@app.command("chroma-check")
def chroma_check() -> None:
    """Check Chroma readiness."""

    status, detail = ChromaVectorRepository.from_settings(get_settings()).check_connection()
    _print_check("Chroma", status, detail)


@app.command("graph-check")
def graph_check() -> None:
    """Check Neo4j readiness with a temporary node."""

    repository = Neo4jGraphRepository(get_settings())
    try:
        status, detail = repository.run_graph_check()
    finally:
        repository.close()
    _print_check("Neo4j", status, detail)


@app.command("health-check")
def health_check() -> None:
    """Check PostgreSQL, Chroma, and Neo4j together."""

    settings = get_settings()
    postgres = asyncio.run(PostgresKnowledgeRepository.from_settings(settings).check_connection())
    chroma = ChromaVectorRepository.from_settings(settings).check_connection()
    graph_repo = Neo4jGraphRepository(settings)
    try:
        graph = graph_repo.run_graph_check()
    finally:
        graph_repo.close()
    table = Table(title="GraphRAG Health")
    table.add_column("Service")
    table.add_column("Status")
    table.add_column("Detail")
    failures = 0
    for service, (status, detail) in {
        "PostgreSQL": postgres,
        "Chroma": chroma,
        "Neo4j": graph,
    }.items():
        table.add_row(service, "[green]PASS[/green]" if status else "[red]FAIL[/red]", detail)
        failures += 0 if status else 1
    console.print(table)
    if failures:
        raise typer.Exit(code=1)


@app.command("hf-check")
def hf_check(
    load_model: Annotated[
        bool,
        typer.Option("--load-model", help="Attempt tokenizer and model loading."),
    ] = False,
) -> None:
    """Check local Hugging Face reasoning readiness."""

    settings = get_settings()
    report = inspect_hf_reasoning_environment(settings)
    _print_hf_reasoning_report(report)

    failed = False
    if not report.dependencies_ready:
        failed = True
        console.print(f"[red]FAIL[/red] {format_hf_reasoning_preflight_error(report)}")
    if report.torch_cpu_only_with_nvidia_driver:
        console.print(
            "[yellow]WARN[/yellow] NVIDIA driver detected, but the current PyTorch "
            f"installation is CPU-only. {HF_REASONING_GPU_INSTALL_HINT}"
        )
        if report.gpu_install_command:
            console.print(
                f"[yellow]INFO[/yellow] GPU install command: {report.gpu_install_command}"
            )

    if load_model and report.dependencies_ready:
        try:
            HuggingFaceReasoningClient(settings)._load_model()
        except MultiAgenticRagError as exc:
            failed = True
            console.print(f"[red]FAIL[/red] Model load failed: {exc}")
        else:
            console.print("[green]PASS[/green] Model load succeeded.")
    elif load_model:
        console.print("[yellow]SKIP[/yellow] Model load skipped because preflight failed.")
    else:
        console.print("[yellow]SKIP[/yellow] Model load skipped. Use --load-model to test it.")

    if failed:
        raise typer.Exit(code=1)


def _alembic_revision_status(dsn: str | None = None) -> tuple[bool, str]:
    current_returncode, current_detail = _run_alembic(["current"])
    heads_returncode, heads_detail = _run_alembic(["heads"])
    if current_returncode != 0:
        return False, f"current unavailable: {current_detail}"
    if heads_returncode != 0:
        return False, f"head unavailable: {heads_detail}"
    current = _parse_revision(current_detail)
    head = _parse_revision(heads_detail)
    if not current or not head:
        target = f" for POSTGRES_DSN={redact_secrets(dsn)}" if dsn else ""
        return (
            False,
            "no Alembic revision found"
            f"{target}; verify the DSN points at the migrated database or run "
            "`uv run --no-sync alembic upgrade head`.",
        )
    if current != head:
        return (
            False,
            f"current={current}, head={head}; run `uv run --no-sync alembic upgrade head`.",
        )
    return True, f"current={current}, head={head}"


def _run_alembic(args: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return 1, str(exc)
    output = (result.stdout or result.stderr).strip()
    return result.returncode, output or f"alembic exited {result.returncode}"


def _parse_revision(output: str) -> str | None:
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("INFO"):
            continue
        return stripped.split()[0]
    return None


async def _ingest_many(
    files: list[Path],
    *,
    system: str,
    version: str,
    kb: str,
    model: ReasoningModelSelector | None,
    review_facts: bool,
) -> list[tuple[Path, dict[str, Any] | None, str | None]]:
    settings = get_settings()
    agent = _build_ingestion_agent(
        model,
        settings=settings,
        review_facts=review_facts,
    )
    results: list[tuple[Path, dict[str, Any] | None, str | None]] = []
    for path in files:
        try:
            result = await agent.ingest(path, kb, system=system, version=version)
        except MultiAgenticRagError as exc:
            results.append((path, None, str(exc)))
            continue
        results.append((path, result.model_dump(), None))
    return results


def _build_ingestion_agent(
    model_selector: ReasoningModelSelector | None = None,
    *,
    settings: Settings | None = None,
    reasoning_client: ReasoningClient | None = None,
    review_facts: bool = False,
) -> KnowledgeBaseStoringAgent:
    loaded_settings = settings or get_settings()
    if review_facts and reasoning_client is None:
        reasoning_client = build_reasoning_client(loaded_settings, model_selector)
    return KnowledgeBaseStoringAgent(
        settings=loaded_settings,
        fact_review_client=reasoning_client if review_facts else None,
        review_facts=review_facts,
    )


def _document_files(directory_path: Path, *, recursive: bool) -> list[Path]:
    directory = directory_path.expanduser().resolve()
    if not directory.exists() or not directory.is_dir():
        raise typer.BadParameter(f"Directory does not exist: {directory}")
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in directory.glob(pattern)
        if path.is_file() and path.suffix.lower() in SUPPORTED_DOCUMENT_SUFFIXES
    )


def _delete_runtime_cache(settings: Settings) -> tuple[list[Path], list[tuple[Path, str]]]:
    raw_paths = [
        settings.global_cache_dir,
        settings.multi_agentic_rag_home,
        settings.document_store_path,
        settings.object_store_path,
        settings.manifest_store_path,
        settings.chroma_path,
        settings.database_cache_dir,
        settings.graph_cache_dir,
        Path(".cache"),
        Path(".multi_agentic_rag"),
    ]
    paths: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path).expanduser().resolve()
        if any(path == parent or path.is_relative_to(parent) for parent in paths):
            continue
        paths.append(path)
    deleted: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    for path in paths:
        if not path.exists():
            continue
        error = _delete_path_with_retries(path)
        if error is not None:
            skipped.append((path, error))
            continue
        deleted.append(path)
    return deleted, skipped


def _delete_path_with_retries(path: Path, *, attempts: int = 6) -> str | None:
    last_error: OSError | None = None
    for attempt in range(attempts):
        try:
            if path.is_dir():
                shutil.rmtree(path, onexc=_make_writable_and_retry)
            else:
                path.unlink()
            return None
        except OSError as exc:
            last_error = exc
            gc.collect()
            if attempt < attempts - 1:
                time.sleep(0.25 * (attempt + 1))
    if last_error is None:
        return "unknown deletion error"
    return f"{type(last_error).__name__}: {last_error}"


def _make_writable_and_retry(
    function: Callable[[str], None],
    path: str,
    exc: BaseException,
) -> None:
    with suppress(OSError):
        os.chmod(path, stat.S_IWRITE)
    function(path)


def _build_retriever(settings: Settings | None = None) -> HybridKnowledgeRetriever:
    settings = settings or get_settings()
    chroma = ChromaVectorRepository.from_settings(settings)
    graph = Neo4jGraphRepository(settings)
    return HybridKnowledgeRetriever(
        bm25=BM25Retriever(build_lexical_repository(settings)),
        vector=VectorRetriever(chroma),
        graph=GraphRetriever(graph, PostgresKnowledgeRepository.from_settings(settings)),
        reranker=select_reranker(settings),
    )


def _build_answer_agent(
    model_selector: ReasoningModelSelector | None = None,
    *,
    settings: Settings | None = None,
    reasoning_client: ReasoningClient | None = None,
) -> AgentRetrieveAnswer:
    settings = settings or get_settings()
    reasoning_client = reasoning_client or build_reasoning_client(settings, model_selector)
    return AgentRetrieveAnswer(
        _build_retriever(settings),
        reasoning_client,
    )


def _build_user_story_agent(
    model_selector: ReasoningModelSelector | None = None,
    *,
    settings: Settings | None = None,
    reasoning_client: ReasoningClient | None = None,
) -> AgentUserStoryBuilder:
    settings = settings or get_settings()
    reasoning_client = reasoning_client or build_reasoning_client(settings, model_selector)
    postgres = PostgresKnowledgeRepository.from_settings(settings)
    graph = Neo4jGraphRepository(settings)
    application = build_application(
        settings=settings,
        model_selector=model_selector,
        reasoning_client=reasoning_client,
    )
    return AgentUserStoryBuilder(
        _build_retriever(settings),
        reasoning_client,
        settings=settings,
        artifact_audit_repository=postgres,
        graph_repository=graph,
        generation_agent=application.user_story_agent,
    )


def _build_workflow_runner(
    model_selector: ReasoningModelSelector | None = None,
    *,
    review_facts: bool = False,
) -> LangGraphWorkflowRunner:
    settings = get_settings()
    reasoning_client = build_reasoning_client(settings, model_selector)
    postgres = PostgresKnowledgeRepository.from_settings(settings)
    ingestion_agent = _build_ingestion_agent(
        model_selector,
        settings=settings,
        reasoning_client=reasoning_client,
        review_facts=review_facts,
    )
    return LangGraphWorkflowRunner(
        router=IntentRouterAgent(reasoning_client),
        planner=WorkflowPlannerAgent(reasoning_client),
        validator=FlowValidatorAgent(),
        ingest_agent=AgentIngestDocument(ingestion_agent),
        answer_agent=AgentRetrieveAnswer(_build_retriever(settings), reasoning_client),
        user_story_agent=_build_user_story_agent(
            model_selector,
            settings=settings,
            reasoning_client=reasoning_client,
        ),
        audit_repository=postgres,
    )


def _print_agent_failure(messages: list[str]) -> None:
    detail = "\n".join(messages) if messages else "Agent failed."
    console.print(f"[red]FAIL[/red] {detail}")
    if hint := _quota_hint_for_message(detail):
        console.print(f"[yellow]HINT[/yellow] {hint}")
    raise typer.Exit(code=1)


def _print_cli_error(exc: MultiAgenticRagError) -> None:
    detail = str(exc)
    console.print(f"[red]FAIL[/red] {detail}")
    if hint := _quota_hint_for_message(detail):
        console.print(f"[yellow]HINT[/yellow] {hint}")
    raise typer.Exit(code=1) from exc


def _quota_hint_for_message(message: str) -> str | None:
    lowered = message.lower()
    if "openai" not in lowered:
        return None
    markers = ("insufficient_quota", "http 429", "error code: 429", "status_code=429")
    if any(marker in lowered for marker in markers):
        return OPENAI_QUOTA_HINT
    return None


def _print_graph_paths(results: list[Any]) -> None:
    printed = False
    for result in results:
        matches = result.metadata.get("graph_matches") or []
        if not matches:
            continue
        if not printed:
            console.print("\n[bold]Graph Paths[/bold]")
            printed = True
        console.print(f"[bold]{result.chunk_id}[/bold]")
        for match in matches:
            reason = str(match.get("reason") or "graph match")
            path = " -> ".join(str(part) for part in match.get("path") or [])
            terms = ", ".join(str(term) for term in match.get("matched_terms") or [])
            suffix = f" [{terms}]" if terms else ""
            console.print(f"- {reason}: {path}{suffix}")
    if not printed:
        console.print("\n[yellow]No graph paths attached to these results.[/yellow]")


def _print_check(service: str, status: bool, detail: str) -> None:
    console.print(f"{service}: {'PASS' if status else 'FAIL'} - {detail}")
    if not status:
        raise typer.Exit(code=1)


def _print_hf_reasoning_report(report: HFReasoningEnvironmentReport) -> None:
    settings_table = Table(title="Hugging Face Reasoning")
    settings_table.add_column("Setting")
    settings_table.add_column("Value")
    settings_table.add_row("HF_REASON_MODEL", report.model)
    settings_table.add_row("HF_REASON_DEVICE", report.device)
    settings_table.add_row("HF_REASON_DTYPE", report.dtype)
    settings_table.add_row("HF_REASON_MAX_NEW_TOKENS", str(report.max_new_tokens))
    settings_table.add_row(
        "HF_REASON_VALIDATION_MAX_NEW_TOKENS",
        str(report.validation_max_new_tokens),
    )
    settings_table.add_row("HF_REASON_TIMEOUT_SECONDS", str(report.timeout_seconds))
    settings_table.add_row("HF_REASON_ANSWER_MODE", report.answer_mode)
    settings_table.add_row("HF_REASON_CACHE_DIR", str(report.cache_dir))
    settings_table.add_row("HF_TOKEN", "present" if report.token_present else "missing")
    settings_table.add_row("ingest fact review", report.fact_review_policy)
    settings_table.add_row(
        "accelerate required",
        "yes" if report.accelerate_required else "no",
    )
    settings_table.add_row("torch", report.torch_version or "not importable")
    settings_table.add_row("torch build", report.torch_build_label)
    settings_table.add_row("torch CUDA build", _format_optional_bool(report.torch_cuda_built))
    settings_table.add_row(
        "nvidia-smi",
        "present" if report.nvidia_smi_available else "not found",
    )
    settings_table.add_row("CUDA", _format_hf_cuda(report))
    settings_table.add_row("CUDA device", report.cuda_device_name or "-")
    if report.gpu_install_command:
        settings_table.add_row("GPU install command", report.gpu_install_command)
    console.print(settings_table)

    dependency_table = Table(title="HF Dependencies")
    dependency_table.add_column("Package")
    dependency_table.add_column("Status")
    dependency_table.add_column("Version")
    dependency_table.add_column("Detail")
    for dependency in report.dependencies:
        dependency_table.add_row(
            dependency.name,
            "[green]PASS[/green]" if dependency.installed else "[red]FAIL[/red]",
            dependency.version or "-",
            dependency.error or "",
        )
    console.print(dependency_table)


def _format_hf_cuda(report: HFReasoningEnvironmentReport) -> str:
    if report.cuda_available is None:
        return "unknown"
    if not report.cuda_available:
        return "not available"
    device_count = "unknown" if report.cuda_device_count is None else str(report.cuda_device_count)
    cuda_version = f", CUDA {report.cuda_version}" if report.cuda_version else ""
    return f"available ({device_count} device(s){cuda_version})"


def _format_optional_bool(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"




if __name__ == "__main__":
    app()
