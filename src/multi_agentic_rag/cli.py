"""Typer command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from multi_agentic_rag.config import get_settings
from multi_agentic_rag.coverage import DEFAULT_SCENARIO_COUNT, plan_requirement_coverage
from multi_agentic_rag.exceptions import IngestionError
from multi_agentic_rag.ingestion import ingest_document
from multi_agentic_rag.models import DocumentStatus, TaskResult, TestExecutionResult
from multi_agentic_rag.retrieval import answer_query
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore
from multi_agentic_rag.storage.cleanup import clean_system_state
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.storage.vector_factory import select_vector_store
from multi_agentic_rag.tasks import handle_task
from multi_agentic_rag.testing import generate_testcases, get_last_test_result, run_testcases
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
    console.print(f"Objects: {paths['objects']}")
    console.print(f"Exports: {paths['exports']}")
    console.print(f"SQLite registry: {paths['registry']}")
    try:
        selection = select_vector_store(settings)
        console.print(f"Vector provider: {selection.provider} ({selection.reason})")
    except Exception as exc:
        console.print(f"[yellow]WARN[/yellow] Vector provider not ready: {exc}")
    console.print("\nNext steps:")
    console.print("1. Create or edit .env with local settings.")
    console.print("2. Start Neo4j manually from Neo4j Desktop if graph indexing is needed.")
    console.print("3. Run: multi-agentic-rag doctor")


@app.command("doctor")
def doctor(
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Treat WARN checks as command failures."),
    ] = False,
    target_graphrag: Annotated[
        bool,
        typer.Option(
            "--target-graphrag",
            help="Run strict Option-4 GraphRAG target checks.",
        ),
    ] = False,
    system: Annotated[
        str | None,
        typer.Option("--system", help="System name for target graph-population checks."),
    ] = None,
    version: Annotated[
        str | None,
        typer.Option("--version", help="Version for target graph-population checks."),
    ] = None,
) -> None:
    """Validate local environment and optional services."""

    checks = run_diagnostics(
        target_graphrag=target_graphrag,
        system_name=system,
        version=version,
    )
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
    path: Annotated[Path, typer.Argument(help="Path to PDF or DOCX document.")],
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str, typer.Option("--version", help="Document version.")],
) -> None:
    """Ingest a versioned PDF or DOCX document."""

    result = ingest_document(path, system_name=system, version=version)
    console.print(f"[green]Ingested[/green] {result.document.source_name}")
    console.print(f"Document ID: {result.document.document_id}")
    console.print(f"Status: {result.document.status.value}")
    console.print(f"Chunks indexed: {result.chunks_indexed}")
    console.print(f"Facts extracted: {result.facts_extracted}")
    console.print(f"Deltas created: {result.deltas_created}")
    console.print(f"Vector store: {result.vector_store}")
    console.print(f"Keyword indexed: {result.keyword_indexed}")
    if result.object_store_path:
        console.print(f"Parsed artifact: {result.object_store_path}")
    console.print(f"Neo4j available: {result.neo4j_available}")
    for warning in result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")


@app.command("ingest-doc")
def ingest_doc(
    path: Annotated[Path, typer.Argument(help="Path to PDF or DOCX document.")],
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str, typer.Option("--version", help="Document version.")],
) -> None:
    """Alias for ingesting a versioned PDF or DOCX document."""

    ingest(path=path, system=system, version=version)


@app.command("ingest-folder")
def ingest_folder(
    folder: Annotated[Path, typer.Argument(help="Folder containing PDF/DOCX documents.")],
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str, typer.Option("--version", help="Document version.")],
) -> None:
    """Ingest every supported document in a folder for the same system/version."""

    if not folder.exists() or not folder.is_dir():
        console.print(f"[red]Folder does not exist:[/red] {folder}")
        raise typer.Exit(code=1)
    supported = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".docx"}
    )
    if not supported:
        console.print("[yellow]No supported .pdf or .docx files found.[/yellow]")
        raise typer.Exit(code=1)
    table = Table(title="Folder Ingestion")
    table.add_column("File")
    table.add_column("Status")
    table.add_column("Chunks")
    table.add_column("Facts")
    for path in supported:
        result = ingest_document(path, system_name=system, version=version)
        table.add_row(
            path.name,
            result.document.status.value,
            str(result.chunks_indexed),
            str(result.facts_extracted),
        )
        for warning in result.warnings:
            console.print(f"[yellow]WARN[/yellow] {path.name}: {warning}")
    console.print(table)


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
    version: Annotated[str | None, typer.Option("--version", help="Specific version.")] = None,
    count: Annotated[int, typer.Option("--count", help="Scenario count.")] = DEFAULT_SCENARIO_COUNT,
) -> None:
    """Generate or reuse tracked coverage records."""

    result = plan_requirement_coverage(
        system_name=system,
        version=version,
        scenario_count=count,
    )
    if not result.supported:
        console.print(f"[yellow]{result.message}[/yellow]")
        return
    table = Table(title="Coverage Records")
    table.add_column("Requirement")
    table.add_column("Index")
    table.add_column("Scenario")
    table.add_column("Status")
    table.add_column("Priority")
    for record in result.records:
        table.add_row(
            record.requirement_id,
            str(record.scenario_index or ""),
            record.test_scenario,
            record.coverage_status,
            record.priority,
        )
    console.print(table)
    console.print(f"{result.action}: {result.message}")


@app.command("coverage-plan")
def coverage_plan(
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str | None, typer.Option("--version", help="Specific version.")] = None,
    count: Annotated[int, typer.Option("--count", help="Scenario count.")] = DEFAULT_SCENARIO_COUNT,
    force: Annotated[bool, typer.Option("--force", help="Regenerate even if covered.")] = False,
) -> None:
    """Generate or reuse tracked coverage scenarios."""

    result = plan_requirement_coverage(
        system_name=system,
        version=version,
        scenario_count=count,
        force=force,
    )
    console.print(f"{result.action}: {result.message}")
    if result.run:
        console.print(f"Run ID: {result.run.run_id}")
        console.print(f"Scope hash: {result.run.scope_hash}")
        console.print(f"Generated count: {result.run.generated_count}")
    if not result.supported:
        raise typer.Exit(code=1)


@app.command("generate-tests")
def generate_tests(
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str | None, typer.Option("--version", help="Specific version.")] = None,
    count: Annotated[int, typer.Option("--count", help="Scenario count.")] = DEFAULT_SCENARIO_COUNT,
    force: Annotated[bool, typer.Option("--force", help="Rewrite generated file.")] = False,
    mock: Annotated[
        bool,
        typer.Option("--mock", help="Generate explicit mock-device tests with no real connection."),
    ] = False,
    execution_mode: Annotated[
        str | None,
        typer.Option("--execution-mode", help="Execution mode: mock, simulator, real, or auto."),
    ] = None,
) -> None:
    """Generate or reuse a pytest testcase file from coverage evidence."""

    result = generate_testcases(
        system_name=system,
        version=version,
        scenario_count=count,
        force=force,
        execution_mode=_resolve_execution_mode(mock=mock, execution_mode=execution_mode),
    )
    console.print(f"{result.action}: {result.message}")
    if result.test_file:
        console.print(f"Test file: {result.test_file.file_path}")
    if not result.supported:
        raise typer.Exit(code=1)


@app.command("run-testcases")
def run_testcases_command(
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str | None, typer.Option("--version", help="Specific version.")] = None,
    count: Annotated[int, typer.Option("--count", help="Scenario count.")] = DEFAULT_SCENARIO_COUNT,
    force_run_all: Annotated[
        bool,
        typer.Option("--force-run-all", help="Execute unchanged scenarios instead of skipping them."),
    ] = False,
    mock: Annotated[
        bool,
        typer.Option("--mock", help="Run generated testcases in explicit mock-device mode."),
    ] = False,
    execution_mode: Annotated[
        str | None,
        typer.Option("--execution-mode", help="Execution mode: mock, simulator, real, or auto."),
    ] = None,
) -> None:
    """Run the generated pytest testcase file and store results."""

    result = run_testcases(
        system_name=system,
        version=version,
        scenario_count=count,
        force_run_all=force_run_all,
        execution_mode=_resolve_execution_mode(mock=mock, execution_mode=execution_mode),
    )
    _print_test_execution(result)
    if not result.supported:
        raise typer.Exit(code=1)


@app.command("last-results")
def last_results(
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str | None, typer.Option("--version", help="Specific version.")] = None,
) -> None:
    """Show the last stored testcase execution result without rerunning."""

    result = get_last_test_result(system_name=system, version=version)
    _print_test_execution(result)
    if not result.supported:
        raise typer.Exit(code=1)


@app.command("clean-system-state")
def clean_system_state_command(
    system: Annotated[str, typer.Option("--system", help="System name to remove.")],
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm deletion of this system's local runtime state."),
    ] = False,
    include_neo4j: Annotated[
        bool,
        typer.Option("--include-neo4j/--skip-neo4j", help="Delete matching Neo4j graph nodes."),
    ] = True,
    include_generated: Annotated[
        bool,
        typer.Option(
            "--include-generated/--keep-generated",
            help="Delete generated/<system>/ automation artifacts.",
        ),
    ] = True,
) -> None:
    """Remove one system from SQLite, Chroma, optional Neo4j, and generated artifacts."""

    if not yes:
        console.print(
            "[yellow]Refusing to delete without --yes.[/yellow] "
            "This command removes local runtime state for exactly one system."
        )
        raise typer.Exit(code=1)
    result = clean_system_state(
        system,
        include_neo4j=include_neo4j,
        include_generated=include_generated,
    )
    table = Table(title=f"Cleaned System State: {result.system_name}")
    table.add_column("Store")
    table.add_column("Deleted")
    for table_name, count in result.sqlite_deleted.items():
        table.add_row(f"sqlite:{table_name}", str(count))
    table.add_row("chroma", "" if result.chroma_deleted is None else str(result.chroma_deleted))
    table.add_row("neo4j", "" if result.neo4j_deleted is None else str(result.neo4j_deleted))
    table.add_row("files", str(len(result.files_deleted)))
    console.print(table)
    for path in result.files_deleted:
        console.print(f"Deleted: {path}")
    for warning in result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")


@app.command("task")
def task(
    user_request: Annotated[str, typer.Argument(help="Natural-language MARAG task.")],
    system: Annotated[str, typer.Option("--system", help="System name.")],
    version: Annotated[str | None, typer.Option("--version", help="Specific version.")] = None,
    count: Annotated[int, typer.Option("--count", help="Scenario count.")] = DEFAULT_SCENARIO_COUNT,
    mock: Annotated[
        bool,
        typer.Option("--mock", help="Route the task with explicit mock-device execution mode."),
    ] = False,
    execution_mode: Annotated[
        str | None,
        typer.Option("--execution-mode", help="Execution mode: mock, simulator, real, or auto."),
    ] = None,
) -> None:
    """Route a natural-language request to query, coverage, writer, or runner agents."""

    result = handle_task(
        user_request,
        system_name=system,
        version=version,
        scenario_count=count,
        execution_mode=_resolve_execution_mode(mock=mock, execution_mode=execution_mode),
    )
    _print_task_result(result)
    if not result.supported:
        raise typer.Exit(code=1)


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
    table.add_row("Vector provider", summary.vector_provider)
    table.add_row("Vector write status", summary.chroma_write_status)
    table.add_row("Keyword index status", summary.keyword_index_status)
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


def _print_test_execution(result: TestExecutionResult) -> None:
    style = "green" if result.supported else "yellow"
    console.print(f"[{style}]{result.action}: {result.message}[/{style}]")
    if result.test_file:
        console.print(f"Test file: {result.test_file.file_path}")
    if result.result:
        table = Table(title="Test Run Result")
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("status", result.result.status)
        table.add_row("exit_code", "" if result.result.exit_code is None else str(result.result.exit_code))
        table.add_row("passed", str(result.result.passed))
        table.add_row("failed", str(result.result.failed))
        table.add_row("skipped", str(result.result.skipped))
        table.add_row("blocked", str(result.result.blocked))
        table.add_row("xml_report_path", result.result.xml_report_path or "")
        table.add_row("duration_seconds", f"{result.result.duration_seconds:.3f}")
        table.add_row("created_at", result.result.created_at)
        console.print(table)
    for warning in result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")


def _print_task_result(result: TaskResult) -> None:
    style = "green" if result.supported else "yellow"
    console.print(f"[{style}]{result.intent}: {result.message}[/{style}]")
    if result.query and result.query.evidence:
        console.print("\nEvidence:")
        for evidence in result.query.evidence[:10]:
            console.print(
                f"- {evidence.source_name} p.{evidence.page} "
                f"({evidence.version}, {evidence.chunk_id})"
            )
    if result.coverage and result.coverage.run:
        console.print(f"Coverage run: {result.coverage.run.run_id}")
        console.print(f"Coverage records: {len(result.coverage.records)}")
    if result.test_generation and result.test_generation.test_file:
        console.print(f"Test file: {result.test_generation.test_file.file_path}")
    if result.test_execution:
        _print_test_execution(result.test_execution)
    if result.automation:
        artifacts = result.automation.generated_artifacts
        if artifacts.pytest_files or artifacts.robot_files or artifacts.json_sidecars:
            console.print("\nArtifacts:")
        for path in artifacts.pytest_files:
            console.print(f"- pytest file: {path}")
        for path in artifacts.robot_files:
            console.print(f"- robot file: {path}")
        for path in artifacts.json_sidecars:
            console.print(f"- json sidecar: {path}")
        for path in artifacts.xml_reports:
            console.print(f"- pytest xml: {path}")
        for path in artifacts.coverage_reports:
            console.print(f"- coverage report: {path}")
        summary = result.automation.execution_summary
        if any(
            [
                summary.executed,
                summary.passed,
                summary.failed,
                summary.skipped,
                summary.blocked,
                summary.skipped_unchanged,
                summary.reused_from_previous_version,
            ]
        ):
            console.print("\nExecution:")
            console.print(f"- executed: {summary.executed}")
            console.print(f"- reused from previous version: {summary.reused_from_previous_version}")
            console.print(f"- skipped unchanged: {summary.skipped_unchanged}")
            console.print(f"- blocked: {summary.blocked}")
            console.print(f"- failed: {summary.failed}")
            console.print(f"- passed: {summary.passed}")
        console.print(f"\nDatabase: {result.automation.db_update_status}")
    for warning in result.warnings:
        console.print(f"[yellow]WARN[/yellow] {warning}")


def _resolve_execution_mode(*, mock: bool, execution_mode: str | None) -> str | None:
    if mock:
        return "mock"
    if execution_mode is None:
        return None
    mode = execution_mode.strip().lower()
    if mode not in {"mock", "simulator", "real", "auto"}:
        console.print("[red]Invalid execution mode.[/red] Use mock, simulator, real, or auto.")
        raise typer.Exit(code=1)
    return mode


if __name__ == "__main__":
    app()
