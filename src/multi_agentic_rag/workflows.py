"""Local Phase 1.1 workflows used by CLI commands and tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.coverage import generate_requirement_coverage
from multi_agentic_rag.exceptions import IngestionError
from multi_agentic_rag.ingestion import ingest_document
from multi_agentic_rag.ingestion.parser import load_pdf_pages
from multi_agentic_rag.models import (
    CoverageRecord,
    DeltaRecord,
    DocumentRecord,
    DocumentStatus,
    FactRecord,
    QueryResult,
)
from multi_agentic_rag.retrieval import answer_query
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.utils.hashing import sha256_file
from multi_agentic_rag.utils.paths import ensure_runtime_dirs, resolve_path

REAL_BRD_V1_NAME = "SIIMCS_BRD_V1.pdf"
REAL_BRD_V2_NAME = "SIIMCS_BRD_V2.pdf"

DEMO_V1_TEXT = "\n".join(
    (
        "REQ-1 Temperature sensor maximum threshold is 70 C.",
        "Protocol MQTT is used for telemetry.",
        "Controller uses Modbus polling.",
    )
)
DEMO_V2_TEXT = "\n".join(
    (
        "REQ-1 Temperature sensor maximum threshold is 80 C.",
        "Protocol MQTT is used for telemetry.",
        "Controller uses Modbus polling.",
    )
)

GRAPH_CHECK_SYSTEM_NAME = "**MULTI_AGENTIC_RAG_GRAPH_CHECK**"


@dataclass(frozen=True)
class ValidationRow:
    """One validation row for a source BRD file or pair-level check."""

    item: str
    status: str
    detail: str


@dataclass(frozen=True)
class BrdValidationResult:
    """Validation result for exact V1/V2 BRD inputs."""

    source_v1_path: Path
    source_v2_path: Path
    rows: list[ValidationRow]
    v1_hash: str | None = None
    v2_hash: str | None = None

    @property
    def status(self) -> str:
        statuses = {row.status for row in self.rows}
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        return "PASS"


@dataclass(frozen=True)
class DemoPdfResult:
    """Result of deterministic demo PDF generation."""

    v1_path: Path
    v2_path: Path
    success: bool
    error: str | None = None


@dataclass(frozen=True)
class IngestionSummary:
    """Clean summary for ordered V1/V2 ingestion workflows."""

    source_v1_path: Path
    source_v2_path: Path
    active_document: DocumentRecord | None
    superseded_document: DocumentRecord | None
    number_of_chunks: int
    number_of_extracted_facts: int
    number_of_delta_records: int
    neo4j_write_status: str
    chroma_write_status: str
    sqlite_write_status: str
    vector_provider: str = "chroma"
    keyword_index_status: str = "PASS"
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DemoRunResult:
    """End-to-end demo workflow result."""

    pdfs: DemoPdfResult
    summary: IngestionSummary
    current_query: QueryResult
    historical_query: QueryResult
    delta_query: QueryResult
    coverage_records: list[CoverageRecord]
    active_threshold: str | None
    superseded_threshold: str | None
    threshold_delta: DeltaRecord | None


@dataclass(frozen=True)
class GraphCheckResult:
    """Safe Neo4j graph-check result."""

    success: bool
    status: str
    detail: str


def project_root() -> Path:
    """Resolve the repository root from the installed source tree."""

    return Path(__file__).resolve().parents[2]


def resolve_real_brd_paths(root: Path | None = None) -> tuple[Path, Path]:
    """Return the exact real BRD paths without globbing or ambiguous search."""

    base = resolve_path(root or project_root())
    return base / REAL_BRD_V1_NAME, base / REAL_BRD_V2_NAME


def create_demo_pdfs(
    *,
    settings: Settings | None = None,
    overwrite: bool = True,
) -> DemoPdfResult:
    """Create deterministic local demo V1/V2 PDFs using PyMuPDF."""

    settings = settings or get_settings()
    demo_dir = resolve_path(settings.multi_agentic_rag_home) / "demo"
    v1_path = demo_dir / "SIIMCS_DEMO_v1.pdf"
    v2_path = demo_dir / "SIIMCS_DEMO_v2.pdf"
    try:
        demo_dir.mkdir(parents=True, exist_ok=True)
        if overwrite or not v1_path.exists():
            _write_pdf(v1_path, DEMO_V1_TEXT)
        if overwrite or not v2_path.exists():
            _write_pdf(v2_path, DEMO_V2_TEXT)
    except Exception as exc:
        return DemoPdfResult(v1_path=v1_path, v2_path=v2_path, success=False, error=str(exc))
    return DemoPdfResult(v1_path=v1_path, v2_path=v2_path, success=True)


def ensure_demo_pdfs(*, settings: Settings | None = None) -> DemoPdfResult:
    """Create demo PDFs only when one of them is missing."""

    return create_demo_pdfs(settings=settings, overwrite=False)


def validate_brd_inputs(
    *,
    v1_path: Path,
    v2_path: Path,
) -> BrdValidationResult:
    """Validate exact BRD file inputs without ingesting them."""

    rows: list[ValidationRow] = []
    v1_hash = _validate_one_pdf(v1_path, "V1", rows)
    v2_hash = _validate_one_pdf(v2_path, "V2", rows)
    if v1_hash and v2_hash:
        if v1_hash == v2_hash:
            rows.append(
                ValidationRow(
                    item="V1/V2 content hash comparison",
                    status="WARN",
                    detail="Hashes are identical; no meaningful deterministic delta may exist.",
                )
            )
        else:
            rows.append(
                ValidationRow(
                    item="V1/V2 content hash comparison",
                    status="PASS",
                    detail="Hashes differ.",
                )
            )
    return BrdValidationResult(
        source_v1_path=v1_path,
        source_v2_path=v2_path,
        rows=rows,
        v1_hash=v1_hash,
        v2_hash=v2_hash,
    )


def validate_real_brd(*, root: Path | None = None) -> BrdValidationResult:
    """Validate the exact real SIIMCS BRD files."""

    v1_path, v2_path = resolve_real_brd_paths(root)
    return validate_brd_inputs(v1_path=v1_path, v2_path=v2_path)


def ingest_real_brd(
    *,
    settings: Settings | None = None,
    root: Path | None = None,
) -> IngestionSummary:
    """Ingest the exact real SIIMCS BRD V1/V2 files in version order."""

    v1_path, v2_path = resolve_real_brd_paths(root)
    validation = validate_brd_inputs(v1_path=v1_path, v2_path=v2_path)
    if validation.status == "FAIL":
        details = "; ".join(row.detail for row in validation.rows if row.status == "FAIL")
        raise IngestionError(f"Real BRD validation failed: {details}")
    return ingest_version_pair(
        v1_path=v1_path,
        v2_path=v2_path,
        system_name="SIIMCS",
        settings=settings,
    )


def ingest_version_pair(
    *,
    v1_path: Path,
    v2_path: Path,
    system_name: str,
    settings: Settings | None = None,
) -> IngestionSummary:
    """Ingest V1 then V2 and summarize durable registry/vector/graph writes."""

    settings = settings or get_settings()
    ensure_runtime_dirs(settings)
    warnings: list[str] = []
    try:
        result_v1 = ingest_document(v1_path, system_name=system_name, version="v1", settings=settings)
        result_v2 = ingest_document(v2_path, system_name=system_name, version="v2", settings=settings)
    except Exception:
        raise
    warnings.extend(result_v1.warnings)
    warnings.extend(result_v2.warnings)

    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    active_document = registry.get_active_document(system_name)
    superseded_documents = registry.list_documents(
        system_name=system_name,
        status=DocumentStatus.SUPERSEDED,
    )
    superseded_v1_documents = [
        document for document in superseded_documents if document.version == "v1"
    ]
    chunks = registry.list_chunks(system_name=system_name)
    facts = registry.list_facts(system_name=system_name)
    deltas = registry.list_deltas(system_name=system_name)

    return IngestionSummary(
        source_v1_path=resolve_path(v1_path),
        source_v2_path=resolve_path(v2_path),
        active_document=active_document,
        superseded_document=superseded_v1_documents[-1]
        if superseded_v1_documents
        else (superseded_documents[-1] if superseded_documents else None),
        number_of_chunks=len(chunks),
        number_of_extracted_facts=len(facts),
        number_of_delta_records=len(deltas),
        neo4j_write_status="PASS"
        if result_v1.neo4j_available and result_v2.neo4j_available
        else "WARN",
        chroma_write_status="WARN"
        if any("Vector indexing skipped" in warning for warning in warnings)
        else "PASS",
        sqlite_write_status="PASS",
        vector_provider=result_v2.vector_store,
        keyword_index_status="PASS" if result_v2.keyword_indexed else "WARN",
        warnings=warnings,
    )


def run_demo_workflow(*, settings: Settings | None = None) -> DemoRunResult:
    """Run the deterministic SIIMCS_DEMO V1/V2 Option-4 proof."""

    settings = settings or get_settings()
    pdfs = ensure_demo_pdfs(settings=settings)
    if not pdfs.success:
        raise IngestionError(pdfs.error or "Demo PDF generation failed.")

    summary = ingest_version_pair(
        v1_path=pdfs.v1_path,
        v2_path=pdfs.v2_path,
        system_name="SIIMCS_DEMO",
        settings=settings,
    )
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    active_facts = registry.list_facts(system_name="SIIMCS_DEMO", status=DocumentStatus.ACTIVE)
    superseded_facts = registry.list_facts(
        system_name="SIIMCS_DEMO",
        status=DocumentStatus.SUPERSEDED,
    )
    deltas = registry.list_deltas(system_name="SIIMCS_DEMO", from_version="v1", to_version="v2")
    coverage_records = generate_requirement_coverage(
        [fact for fact in active_facts if fact.fact_type == "requirement"]
    )
    registry.upsert_coverage(coverage_records)

    current_query = answer_query(
        "What is the current temperature threshold?",
        system_name="SIIMCS_DEMO",
        settings=settings,
    )
    historical_query = answer_query(
        "What was the old temperature threshold?",
        system_name="SIIMCS_DEMO",
        settings=settings,
    )
    delta_query = answer_query(
        "What changed in temperature threshold?",
        system_name="SIIMCS_DEMO",
        settings=settings,
    )

    return DemoRunResult(
        pdfs=pdfs,
        summary=summary,
        current_query=current_query,
        historical_query=historical_query,
        delta_query=delta_query,
        coverage_records=coverage_records,
        active_threshold=_threshold_value(active_facts),
        superseded_threshold=_threshold_value(superseded_facts),
        threshold_delta=next(
            (delta for delta in deltas if delta.fact_key == "threshold:temperature"),
            None,
        ),
    )


def run_graph_check(
    *,
    settings: Settings | None = None,
    graph_store: Neo4jGraphStore | None = None,
) -> GraphCheckResult:
    """Run the safe graph-check node workflow."""

    store = graph_store or Neo4jGraphStore(settings or get_settings())
    try:
        success, detail = store.run_graph_check(test_system_name=GRAPH_CHECK_SYSTEM_NAME)
    finally:
        store.close()
    return GraphCheckResult(
        success=success,
        status="PASS" if success else "FAIL",
        detail=detail,
    )


def _write_pdf(path: Path, text: str) -> None:
    import fitz

    if path.exists():
        path.unlink()
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), text, fontsize=11)
    document.set_metadata({})
    document.save(path)
    document.close()


def _validate_one_pdf(path: Path, label: str, rows: list[ValidationRow]) -> str | None:
    source = resolve_path(path)
    if not source.exists():
        rows.append(ValidationRow(f"{label} exists", "FAIL", f"Missing: {source}"))
        return None
    rows.append(ValidationRow(f"{label} exists", "PASS", str(source)))
    try:
        with source.open("rb") as file_obj:
            file_obj.read(1)
    except Exception as exc:
        rows.append(ValidationRow(f"{label} readable", "FAIL", str(exc)))
        return None
    rows.append(ValidationRow(f"{label} readable", "PASS", "Readable."))
    if source.suffix.lower() != ".pdf":
        rows.append(ValidationRow(f"{label} supported PDF", "FAIL", "File extension is not .pdf."))
        return None
    try:
        pages = load_pdf_pages(source)
    except Exception as exc:
        rows.append(ValidationRow(f"{label} supported PDF", "FAIL", str(exc)))
        return None
    rows.append(ValidationRow(f"{label} supported PDF", "PASS", "PyMuPDF opened the PDF."))
    extracted_text = "\n".join(page.text for page in pages).strip()
    if not extracted_text:
        rows.append(ValidationRow(f"{label} extractable text", "FAIL", "No text extracted."))
        return None
    rows.append(
        ValidationRow(
            f"{label} extractable text",
            "PASS",
            f"{len(extracted_text)} text characters extracted.",
        )
    )
    content_hash = sha256_file(source)
    rows.append(ValidationRow(f"{label} content hash", "PASS", content_hash))
    return content_hash


def _threshold_value(facts: list[FactRecord]) -> str | None:
    for fact in facts:
        if fact.fact_key == "threshold:temperature":
            return f"{fact.value} {fact.unit}".strip() if fact.unit else fact.value
    return None
