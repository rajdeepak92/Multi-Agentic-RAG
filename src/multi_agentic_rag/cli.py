"""Typer command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from multi_agentic_rag.config import get_settings
from multi_agentic_rag.coverage import generate_requirement_coverage
from multi_agentic_rag.exceptions import IngestionError
from multi_agentic_rag.ingestion import ingest_document
from multi_agentic_rag.models import DocumentStatus
from multi_agentic_rag.retrieval import answer_query
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.utils.diagnostics import DiagnosticCheck, run_diagnostics
from multi_agentic_rag.utils.paths import ensure_runtime_dirs
from multi_agentic_rag.workflows import (
    BrdValidationResult,
    DemoRunResult,
    IngestionSummary,
    create_demo_pdfs,
    ingest_real_brd,
    run_demo_workflow,
    run_graph_check,
    validate_real_brd,
)

app = typer.Typer(
    name="multi-agentic-rag",
    help="Local-first graph-based agentic RAG for versioned engineering documents.",
    no_args_is_help=True,
)
console = Console()


@app.command("init")
def init() -> None:
    """Create local runtime directories and SQLite registry."""

    settings = get_settings()
    paths = ensure_runtime_dirs(settings)
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    console.print("[bold green]Initialized multi-agentic-rag local workspace.[/bold green]")
    console.print(f"Home: {paths['home']}")
    console.print(f"Documents: {paths['documents']}")
    console.print(f"Chroma: {paths['chroma']}")
    console.print(f"Exports: {paths['exports']}")
    console.print(f"SQLite registry: {paths['registry']}")
    console.print("\nNext steps:")
    console.print("1. Copy .env.example to .env and update local settings.")
    console.print("2. Start Neo4j manually from Neo4j Desktop if graph indexing is needed.")
    console.print("3. Run: multi-agentic-rag doctor")


@app.command("doctor")
def doctor(
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Treat WARN checks as command failures."),
    ] = False,
) -> None:
    """Validate local environment and optional services."""

    checks = run_diagnostics()
    _print_checks(checks)
    failure_statuses = {"FAIL", "WARN"} if strict else {"FAIL"}
    if any(check.status in failure_statuses for check in checks):
        raise typer.Exit(code=1)


@app.command("graph-check")
def graph_check() -> None:
    """Safely verify Neo4j graph read/write/delete behavior."""

    result = run_graph_check()
    style = "green" if result.success else "red"
    console.print(f"[{style}]{result.status}[/{style}] {result.detail}")
    if not result.success:
        raise typer.Exit(code=1)


@app.command("demo-pdf")
def demo_pdf() -> None:
    """Generate deterministic local demo V1/V2 PDFs."""

    result = create_demo_pdfs(overwrite=False)
    if not result.success:
        console.print(f"[red]FAIL[/red] {result.error}")
        return
    console.print("[green]PASS[/green] Created demo PDFs")
    console.print(f"V1: {result.v1_path}")
    console.print(f"V2: {result.v2_path}")


@app.command("demo-run")
def demo_run() -> None:
    """Run deterministic local V1/V2 ingestion, delta, query, and coverage proof."""

    try:
        result = run_demo_workflow()
    except IngestionError as exc:
        console.print(f"[red]FAIL[/red] {exc}")
        raise typer.Exit(code=1) from exc
    _print_demo_run(result)


@app.command("validate-real-brd")
def validate_real_brd_command() -> None:
    """Validate exact real SIIMCS BRD V1/V2 PDF inputs without ingesting."""

    result = validate_real_brd()
    _print_validation(result)
    if result.status == "FAIL":
        raise typer.Exit(code=1)


@app.command("ingest-real-brd")
def ingest_real_brd_command() -> None:
    """Ingest exact real SIIMCS BRD V1/V2 files in version order."""

    try:
        summary = ingest_real_brd()
    except IngestionError as exc:
        console.print(f"[red]FAIL[/red] {exc}")
        raise typer.Exit(code=1) from exc
    _print_ingestion_summary(summary)


@app.command("api")
def api(
    host: Annotated[str | None, typer.Option("--host", help="API bind host.")] = None,
    port: Annotated[int | None, typer.Option("--port", help="API bind port.")] = None,
) -> None:
    """Start the local FastAPI service."""

    settings = get_settings()
    graph_store = Neo4jGraphStore(settings)
    available, message = graph_store.check_connection()
    graph_store.close()
    if not available:
        console.print(f"[yellow]WARN[/yellow] Neo4j unavailable: {message}")
    uvicorn.run(
        "multi_agentic_rag.api.main:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=False,
    )


@app.command("ingest")
def ingest(
    path: Annotated[Path, typer.Argument(help="Path to PDF document.")],
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str, typer.Option("--version", help="Document version.")],
) -> None:
    """Ingest a versioned PDF document."""

    result = ingest_document(path, system_name=system, version=version)
    console.print(f"[green]Ingested[/green] {result.document.source_name}")
    console.print(f"Document ID: {result.document.document_id}")
    console.print(f"Status: {result.document.status.value}")
    console.print(f"Chunks indexed: {result.chunks_indexed}")
    console.print(f"Facts extracted: {result.facts_extracted}")
    console.print(f"Deltas created: {result.deltas_created}")
    console.print(f"Neo4j available: {result.neo4j_available}")
    for warning in result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")


@app.command("query")
def query(
    user_query: Annotated[str, typer.Argument(help="Question to answer.")],
    system: Annotated[str | None, typer.Option("--system", help="System name.")] = None,
    version: Annotated[str | None, typer.Option("--version", help="Specific version.")] = None,
) -> None:
    """Query current, historical, or delta-aware evidence."""

    result = answer_query(user_query, system_name=system, version=version)
    style = "green" if result.supported else "yellow"
    console.print(f"[{style}]{result.answer}[/{style}]")
    if result.evidence:
        console.print("\nEvidence:")
        for evidence in result.evidence:
            console.print(
                f"- {evidence.source_name} p.{evidence.page} "
                f"({evidence.version}, {evidence.chunk_id})"
            )
    for warning in result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")


@app.command("delta")
def delta(
    system: Annotated[str, typer.Option("--system", help="System name.")],
    from_version: Annotated[str | None, typer.Option("--from", help="Source version.")] = None,
    to_version: Annotated[str | None, typer.Option("--to", help="Target version.")] = None,
) -> None:
    """Show deterministic deltas."""

    registry = SQLiteRegistry(get_settings().sqlite_db_path)
    registry.initialize()
    records = registry.list_deltas(
        system_name=system,
        from_version=from_version,
        to_version=to_version,
    )
    if not records:
        console.print("[yellow]No delta records found. No impact claim can be made.[/yellow]")
        return
    table = Table(title="Delta Records")
    table.add_column("Type")
    table.add_column("From")
    table.add_column("To")
    table.add_column("Old")
    table.add_column("New")
    table.add_column("Risk")
    for record in records:
        table.add_row(
            record.change_type,
            record.from_version,
            record.to_version,
            record.old_value or "",
            record.new_value or "",
            record.risk_level,
        )
    console.print(table)


@app.command("coverage")
def coverage(
    system: Annotated[str, typer.Option("--system", help="System name.")],
) -> None:
    """Generate baseline coverage records from active requirement evidence."""

    registry = SQLiteRegistry(get_settings().sqlite_db_path)
    registry.initialize()
    requirement_facts = [
        fact
        for fact in registry.list_facts(system_name=system, status=DocumentStatus.ACTIVE)
        if fact.fact_type == "requirement"
    ]
    if not requirement_facts:
        console.print("[yellow]No active requirement evidence found. No coverage claim made.[/yellow]")
        return
    records = generate_requirement_coverage(requirement_facts)
    registry.upsert_coverage(records)
    table = Table(title="Coverage Records")
    table.add_column("Requirement")
    table.add_column("Scenario")
    table.add_column("Status")
    table.add_column("Priority")
    for record in records:
        table.add_row(
            record.requirement_id,
            record.test_scenario,
            record.coverage_status,
            record.priority,
        )
    console.print(table)


@app.command("mcp-info")
def mcp_info() -> None:
    """Print planned MCP architecture for later phases."""

    console.print("[bold]MCP Phase 1 Status[/bold]")
    console.print("MCP is disabled in Phase 1. FastAPI is the active local service boundary.")
    console.print("Future MCP tools/resources/prompts will call the same internal services used now.")
    console.print("\nPlanned MCP tools:")
    for tool_name in (
        "ingest_document",
        "query_current_truth",
        "query_history",
        "compute_delta",
        "generate_coverage",
        "inspect_graph",
    ):
        console.print(f"- {tool_name}")


def _print_checks(checks: list[DiagnosticCheck]) -> None:
    table = Table(title="multi-agentic-rag doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for check in checks:
        style = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}.get(check.status, "white")
        table.add_row(check.name, f"[{style}]{check.status}[/{style}]", check.detail)
    console.print(table)


def _print_validation(result: BrdValidationResult) -> None:
    table = Table(title=f"Real BRD Validation: {result.status}")
    table.add_column("Item")
    table.add_column("Status")
    table.add_column("Detail")
    for row in result.rows:
        style = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}.get(row.status, "white")
        table.add_row(row.item, f"[{style}]{row.status}[/{style}]", row.detail)
    console.print(table)


def _print_ingestion_summary(summary: IngestionSummary) -> None:
    table = Table(title="V1/V2 Ingestion Summary")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("source_v1_path", str(summary.source_v1_path))
    table.add_row("source_v2_path", str(summary.source_v2_path))
    table.add_row(
        "active_document",
        f"{summary.active_document.document_id} ({summary.active_document.version})"
        if summary.active_document
        else "",
    )
    table.add_row(
        "superseded_document",
        f"{summary.superseded_document.document_id} ({summary.superseded_document.version})"
        if summary.superseded_document
        else "",
    )
    table.add_row("number_of_chunks", str(summary.number_of_chunks))
    table.add_row("number_of_extracted_facts", str(summary.number_of_extracted_facts))
    table.add_row("number_of_delta_records", str(summary.number_of_delta_records))
    table.add_row("Neo4j write status", summary.neo4j_write_status)
    table.add_row("Chroma write status", summary.chroma_write_status)
    table.add_row("SQLite write status", summary.sqlite_write_status)
    console.print(table)
    for warning in summary.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")


def _print_demo_run(result: DemoRunResult) -> None:
    console.print("[green]PASS[/green] demo-run completed")
    _print_ingestion_summary(result.summary)
    console.print(f"Demo V1: {result.pdfs.v1_path}")
    console.print(f"Demo V2: {result.pdfs.v2_path}")
    console.print(f"Active threshold: {result.active_threshold}")
    console.print(f"Superseded threshold: {result.superseded_threshold}")
    if result.threshold_delta:
        console.print(
            "Threshold delta: "
            f"{result.threshold_delta.fact_key} changed from "
            f"{result.threshold_delta.old_value} to {result.threshold_delta.new_value}"
        )
    else:
        console.print("[yellow]WARN[/yellow] No threshold delta found.")
    console.print(f"Current query: {result.current_query.answer}")
    console.print(f"Historical query: {result.historical_query.answer}")
    console.print(f"Delta query: {result.delta_query.answer}")
    console.print(f"Coverage draft records: {len(result.coverage_records)}")


if __name__ == "__main__":
    app()
