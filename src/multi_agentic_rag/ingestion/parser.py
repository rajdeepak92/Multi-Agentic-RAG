"""Document parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from multi_agentic_rag.exceptions import IngestionError
from multi_agentic_rag.utils.paths import resolve_path


@dataclass(frozen=True)
class PageText:
    """Text extracted from one source page."""

    page: int
    text: str


def load_pdf_pages(path: str | Path) -> list[PageText]:
    """Load text from a PDF using PyMuPDF."""

    source = resolve_path(path)
    if not source.exists():
        raise IngestionError(f"Document does not exist: {source}")
    if source.suffix.lower() != ".pdf":
        raise IngestionError("Phase 1 ingestion expects PDF documents.")
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - dependency availability
        raise IngestionError("PyMuPDF is required for PDF ingestion.") from exc

    pages: list[PageText] = []
    with fitz.open(source) as document:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                pages.append(PageText(page=index, text=text))
    if not pages:
        raise IngestionError(f"No extractable text found in {source}")
    return pages
