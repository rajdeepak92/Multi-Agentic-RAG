"""Typer command-line interface for the GraphRAG-only runtime."""

from __future__ import annotations

import asyncio
import gc
import os
import shutil
import stat
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from multi_agentic_rag.agents import KnowledgeBaseStoringAgent
from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.exceptions import MultiAgenticRagError
from multi_agentic_rag.infrastructure.chroma import ChromaVectorRepository
from multi_agentic_rag.infrastructure.neo4j import Neo4jGraphRepository
from multi_agentic_rag.infrastructure.postgres import PostgresKnowledgeRepository
from multi_agentic_rag.retrieval import (
    BM25Retriever,
    GraphRetriever,
    HybridKnowledgeRetriever,
    VectorRetriever,
)
from multi_agentic_rag.retrieval.reranker import select_reranker

app = typer.Typer(
    name="multi-agentic-rag",
    help="GraphRAG-only knowledge base ingestion and retrieval.",
    no_args_is_help=True,
)
console = Console()
SUPPORTED_DOCUMENT_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".markdown"}


@app.command("ingest")
def ingest(
    document_path: Annotated[Path, typer.Argument(help="Path to PDF, DOCX, TXT, or Markdown.")],
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str, typer.Option("--version", help="Document version.")],
    kb: Annotated[str, typer.Option("--kb", help="Knowledge base name or context.")] = "default",
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
    """

    try:
        result = asyncio.run(
            KnowledgeBaseStoringAgent().ingest(
                document_path,
                kb,
                system=system,
                version=version,
            )
        )
    except MultiAgenticRagError as exc:
        console.print(f"[red]FAIL[/red] {exc}")
        raise typer.Exit(code=1) from exc
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
        delete_cache: Delete `.multi_agentic_rag` and `.cache` after database
            cleanup. This is intentionally all-or-nothing.
        yes: Required confirmation flag for non-interactive runs.
    """

    if all_data and system:
        console.print("[red]FAIL[/red] Use either --all or --system, not both.")
        raise typer.Exit(code=1)
    if not all_data and not system:
        console.print("[red]FAIL[/red] Provide --system or --all.")
        raise typer.Exit(code=1)
    if all_data and kb:
        console.print("[red]FAIL[/red] --kb can only be used with --system.")
        raise typer.Exit(code=1)
    if delete_cache and not all_data:
        console.print("[red]FAIL[/red] --delete-cache requires --all.")
        raise typer.Exit(code=1)
    if not yes and not typer.confirm("Delete configured GraphRAG state?"):
        raise typer.Exit(code=1)

    settings = get_settings()
    scope_system = None if all_data else system
    scope_kb = None if all_data else kb
    postgres_counts = asyncio.run(
        PostgresKnowledgeRepository.from_settings(settings).clear(
            system_name=scope_system,
            kb_name=scope_kb,
        )
    )
    chroma_repo = ChromaVectorRepository.from_settings(settings)
    try:
        chroma_deleted = chroma_repo.clear(
            system_name=scope_system,
            kb_name=scope_kb,
        )
    finally:
        chroma_repo.close()
    del chroma_repo
    gc.collect()
    graph_repo = Neo4jGraphRepository(settings)
    try:
        graph_ready, graph_message = graph_repo.check_connection()
        if not graph_ready:
            console.print(f"[red]FAIL[/red] Neo4j cleanup unavailable: {graph_message}")
            raise typer.Exit(code=1)
        graph_deleted = graph_repo.clear(system_name=scope_system, kb_name=scope_kb)
    finally:
        graph_repo.close()
    gc.collect()
    deleted_paths, skipped_paths = _delete_runtime_cache(settings) if delete_cache else ([], [])

    table = Table(title="Clean System State")
    table.add_column("Target")
    table.add_column("Deleted")
    table.add_row("PostgreSQL rows", str(sum(postgres_counts.values())))
    table.add_row("Chroma vectors", str(chroma_deleted))
    table.add_row("Neo4j nodes", str(graph_deleted))
    table.add_row("Runtime/cache paths", str(len(deleted_paths)))
    console.print(table)
    if deleted_paths:
        for path in deleted_paths:
            console.print(f"deleted_path: {path}")
    if skipped_paths:
        for path, reason in skipped_paths:
            console.print(f"[yellow]WARN[/yellow] could_not_delete: {path} ({reason})")
        raise typer.Exit(code=1)


def _print_ingest_result(rows: dict) -> None:
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


@app.command("db-check")
def db_check() -> None:
    """Check PostgreSQL readiness."""

    settings = get_settings()
    status, detail = asyncio.run(
        PostgresKnowledgeRepository.from_settings(settings).check_connection()
    )
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


async def _ingest_many(
    files: list[Path],
    *,
    system: str,
    version: str,
    kb: str,
) -> list[tuple[Path, dict | None, str | None]]:
    agent = KnowledgeBaseStoringAgent()
    results: list[tuple[Path, dict | None, str | None]] = []
    for path in files:
        try:
            result = await agent.ingest(path, kb, system=system, version=version)
        except MultiAgenticRagError as exc:
            results.append((path, None, str(exc)))
            continue
        results.append((path, result.model_dump(), None))
    return results


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
        settings.multi_agentic_rag_home,
        settings.document_store_path,
        settings.object_store_path,
        settings.manifest_store_path,
        settings.chroma_path,
        Path(".cache"),
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


def _build_retriever() -> HybridKnowledgeRetriever:
    settings = get_settings()
    postgres = PostgresKnowledgeRepository.from_settings(settings)
    chroma = ChromaVectorRepository.from_settings(settings)
    graph = Neo4jGraphRepository(settings)
    return HybridKnowledgeRetriever(
        bm25=BM25Retriever(postgres),
        vector=VectorRetriever(chroma),
        graph=GraphRetriever(graph, postgres),
        reranker=select_reranker(settings),
    )


def _print_check(service: str, status: bool, detail: str) -> None:
    console.print(f"{service}: {'PASS' if status else 'FAIL'} - {detail}")
    if not status:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
