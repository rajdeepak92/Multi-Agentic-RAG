"""Path helpers for local runtime state."""

from __future__ import annotations

import shutil
from pathlib import Path

from multi_agentic_rag.config import Settings
from multi_agentic_rag.constants import (
    CHROMA_DIR_NAME,
    DOCUMENTS_DIR_NAME,
    EXPORTS_DIR_NAME,
    OBJECTS_DIR_NAME,
)


def resolve_path(path: str | Path) -> Path:
    """Resolve a path relative to the current working directory."""

    return Path(path).expanduser().resolve()


def ensure_runtime_dirs(settings: Settings) -> dict[str, Path]:
    """Create local runtime directories and return their paths."""

    home = resolve_path(settings.multi_agentic_rag_home)
    documents = home / DOCUMENTS_DIR_NAME
    chroma = resolve_path(settings.chroma_path)
    exports = home / EXPORTS_DIR_NAME
    objects = resolve_path(settings.object_store_path)
    for path in (home, documents, exports, objects):
        path.mkdir(parents=True, exist_ok=True)
    if settings.allow_local_dev_mode:
        chroma.mkdir(parents=True, exist_ok=True)
        settings.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
    return {
        "home": home,
        "documents": documents,
        "chroma": chroma,
        "exports": exports,
        OBJECTS_DIR_NAME: objects,
        "registry": resolve_path(settings.sqlite_db_path),
    }


def copy_source_document(
    source_path: str | Path,
    documents_dir: str | Path,
    *,
    system_name: str,
    version: str,
    content_hash: str,
) -> Path:
    """Copy a source document into the managed local documents directory."""

    source = resolve_path(source_path)
    destination_dir = resolve_path(documents_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{system_name}_{version}_{content_hash[:12]}_{source.name}"
    if source != destination:
        shutil.copy2(source, destination)
    return destination
