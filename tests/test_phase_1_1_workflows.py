from pathlib import Path
import shutil

from multi_agentic_rag.config import Settings
from multi_agentic_rag.ingestion.parser import load_pdf_pages
from multi_agentic_rag.models import DocumentStatus
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.workflows import (
    REAL_BRD_V1_NAME,
    REAL_BRD_V2_NAME,
    create_demo_pdfs,
    ingest_real_brd,
    resolve_real_brd_paths,
    run_demo_workflow,
    validate_brd_inputs,
    validate_real_brd,
)


def test_demo_pdf_generation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    result = create_demo_pdfs(settings=settings)

    assert result.success
    assert result.v1_path.exists()
    assert result.v2_path.exists()
    v1_text = "\n".join(page.text for page in load_pdf_pages(result.v1_path))
    v2_text = "\n".join(page.text for page in load_pdf_pages(result.v2_path))
    assert "70 C" in v1_text
    assert "80 C" in v2_text


def test_exact_real_brd_path_resolution_uses_expected_names(tmp_path: Path) -> None:
    v1_path, v2_path = resolve_real_brd_paths(tmp_path)

    assert v1_path == tmp_path.resolve() / REAL_BRD_V1_NAME
    assert v2_path == tmp_path.resolve() / REAL_BRD_V2_NAME


def test_real_brd_validation_logic_with_temp_pdfs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    demo = create_demo_pdfs(settings=settings)

    result = validate_brd_inputs(v1_path=demo.v1_path, v2_path=demo.v2_path)

    assert result.status == "PASS"
    assert result.v1_hash
    assert result.v2_hash
    assert result.v1_hash != result.v2_hash


def test_real_brd_ingestion_path_selection_logic(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    real_root = tmp_path / "project"
    real_root.mkdir()
    demo = create_demo_pdfs(settings=settings)
    shutil.copyfile(demo.v1_path, real_root / REAL_BRD_V1_NAME)
    shutil.copyfile(demo.v2_path, real_root / REAL_BRD_V2_NAME)

    validation = validate_real_brd(root=real_root)
    summary = ingest_real_brd(settings=settings, root=real_root)

    assert validation.status == "PASS"
    assert summary.source_v1_path == (real_root / REAL_BRD_V1_NAME).resolve()
    assert summary.source_v2_path == (real_root / REAL_BRD_V2_NAME).resolve()
    assert summary.active_document is not None
    assert summary.active_document.version == "v2"


def test_demo_v1_v2_lifecycle_delta_queries_and_no_hard_delete(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    result = run_demo_workflow(settings=settings)
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()

    documents = registry.list_documents(system_name="SIIMCS_DEMO")
    active = registry.get_active_document("SIIMCS_DEMO")
    superseded = registry.list_documents(
        system_name="SIIMCS_DEMO",
        status=DocumentStatus.SUPERSEDED,
    )

    assert len(documents) == 2
    assert active is not None
    assert active.version == "v2"
    assert superseded[0].version == "v1"
    assert result.active_threshold == "80 C"
    assert result.superseded_threshold == "70 C"
    assert result.threshold_delta is not None
    assert result.threshold_delta.old_value == "70 C"
    assert result.threshold_delta.new_value == "80 C"
    assert "80 C" in result.current_query.answer
    assert "70 C" not in result.current_query.answer
    assert "70 C" in result.historical_query.answer
    assert "threshold:temperature changed from 70 C to 80 C" in result.delta_query.answer


def test_repeated_demo_run_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    first = run_demo_workflow(settings=settings)
    second = run_demo_workflow(settings=settings)

    assert second.summary.number_of_chunks == first.summary.number_of_chunks
    assert second.summary.number_of_extracted_facts == first.summary.number_of_extracted_facts
    assert second.summary.number_of_delta_records == first.summary.number_of_delta_records
    assert second.active_threshold == "80 C"
    assert second.superseded_threshold == "70 C"


def test_repeated_real_ingestion_is_idempotent_with_temp_exact_files(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    real_root = tmp_path / "project"
    real_root.mkdir()
    demo = create_demo_pdfs(settings=settings)
    shutil.copyfile(demo.v1_path, real_root / REAL_BRD_V1_NAME)
    shutil.copyfile(demo.v2_path, real_root / REAL_BRD_V2_NAME)

    first = ingest_real_brd(settings=settings, root=real_root)
    second = ingest_real_brd(settings=settings, root=real_root)

    assert second.number_of_chunks == first.number_of_chunks
    assert second.number_of_extracted_facts == first.number_of_extracted_facts
    assert second.number_of_delta_records == first.number_of_delta_records
    assert second.active_document is not None
    assert second.active_document.version == "v2"
    assert second.superseded_document is not None
    assert second.superseded_document.version == "v1"


def _settings(tmp_path: Path) -> Settings:
    runtime = tmp_path / ".runtime"
    return Settings(
        multi_agentic_rag_home=runtime,
        sqlite_db_path=runtime / "registry.db",
        chroma_path=runtime / "chroma",
        neo4j_uri=None,
    )
