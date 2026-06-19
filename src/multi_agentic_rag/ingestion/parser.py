"""Document parsing helpers for PDF, DOCX, TXT, and Markdown."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from multi_agentic_rag.domain import PageText
from multi_agentic_rag.exceptions import IngestionError


def load_document_pages(
    path: str | Path,
    *,
    enable_ocr: bool = False,
    tesseract_cmd: str | None = None,
) -> list[PageText]:
    """Load supported source document pages.

    Args:
        path: Source file path. Supported suffixes are `.pdf`, `.docx`, `.txt`,
            `.md`, and `.markdown`.
        enable_ocr: Whether to attempt OCR for PDF pages without text.
        tesseract_cmd: Optional Tesseract executable path.

    Returns:
        Parsed page records.

    Raises:
        IngestionError: If the file is missing, unsupported, or has no text.
    """

    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise IngestionError(f"Document does not exist: {source}")
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        return load_pdf_pages(source, enable_ocr=enable_ocr, tesseract_cmd=tesseract_cmd)
    if suffix == ".docx":
        return load_docx_pages(source)
    if suffix in {".txt", ".md", ".markdown"}:
        return load_text_pages(source)
    raise IngestionError("Supported document types are .pdf, .docx, .txt, .md, and .markdown.")


def load_text_pages(path: str | Path) -> list[PageText]:
    """Load a TXT or Markdown document as one logical page.

    Args:
        path: Source `.txt`, `.md`, or `.markdown` path.

    Returns:
        One logical page containing the file text.

    Raises:
        IngestionError: If no text can be read.
    """

    source = Path(path).expanduser().resolve()
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        raise IngestionError(f"No extractable text found in {source}")
    method = "markdown" if source.suffix.lower() in {".md", ".markdown"} else "text"
    return [PageText(page=1, text=text, extraction_method=method)]


def load_docx_pages(path: str | Path) -> list[PageText]:
    """Load paragraphs and tables from a DOCX document.

    Args:
        path: Source `.docx` path.

    Returns:
        One logical page containing ordered paragraphs and rendered tables.

    Raises:
        IngestionError: If the document has no extractable text.
    """

    source = Path(path).expanduser().resolve()
    docx = import_module("docx")
    document = docx.Document(str(source))
    parts: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            parts.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    text = "\n".join(parts).strip()
    if not text:
        raise IngestionError(f"No extractable text found in {source}")
    return [PageText(page=1, text=text, extraction_method="python-docx")]


def load_pdf_pages(
    path: str | Path,
    *,
    enable_ocr: bool = False,
    tesseract_cmd: str | None = None,
) -> list[PageText]:
    """Load text and table context from a PDF.

    Args:
        path: Source `.pdf` path.
        enable_ocr: Whether to OCR pages with no extractable text.
        tesseract_cmd: Optional Tesseract executable path.

    Returns:
        Page records with text and optional rendered table content.

    Raises:
        IngestionError: If the PDF has no extractable text.
    """

    source = Path(path).expanduser().resolve()
    fitz = import_module("fitz")
    table_text_by_page = _load_pdf_tables(source)
    pages: list[PageText] = []
    with fitz.open(source) as document:
        for index, page in enumerate(document, start=1):
            text = str(page.get_text("text")).strip()
            method = "pymupdf"
            if not text and enable_ocr:
                text = _ocr_page(page, tesseract_cmd=tesseract_cmd)
                if text:
                    method = "tesseract"
            tables = table_text_by_page.get(index, [])
            combined = "\n\n".join(part for part in [text, *tables] if part).strip()
            if combined:
                pages.append(
                    PageText(page=index, text=combined, tables=tables, extraction_method=method)
                )
    if not pages:
        raise IngestionError(f"No extractable text found in {source}")
    return pages


def _load_pdf_tables(path: Path) -> dict[int, list[str]]:
    try:
        pdfplumber = import_module("pdfplumber")
    except Exception:
        return {}
    tables_by_page: dict[int, list[str]] = {}
    try:
        with pdfplumber.open(path) as document:
            for index, page in enumerate(document.pages, start=1):
                page_tables = []
                for table in page.extract_tables() or []:
                    rows = [
                        " | ".join((cell or "").strip() for cell in row).strip()
                        for row in table
                        if row
                    ]
                    rendered = "\n".join(row for row in rows if row)
                    if rendered:
                        page_tables.append(rendered)
                if page_tables:
                    tables_by_page[index] = page_tables
    except Exception:
        return {}
    return tables_by_page


def _ocr_page(page: Any, *, tesseract_cmd: str | None) -> str:
    try:
        fitz = import_module("fitz")
        image_module = import_module("PIL.Image")
        pytesseract = import_module("pytesseract")
    except Exception:
        return ""
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    try:
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = image_module.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        return str(pytesseract.image_to_string(image)).strip()
    except Exception:
        return ""
