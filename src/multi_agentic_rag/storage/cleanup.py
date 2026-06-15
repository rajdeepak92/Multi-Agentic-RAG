"""Scoped cleanup utilities for local MARAG runtime state."""

from __future__ import annotations

from dataclasses import dataclass, field
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from multi_agentic_rag.config import Settings, get_settings
from multi_agentic_rag.storage.neo4j_store import Neo4jGraphStore
from multi_agentic_rag.storage.sqlite_registry import SQLiteRegistry
from multi_agentic_rag.storage.vector_factory import select_vector_store
from multi_agentic_rag.testing.generator import DEFAULT_OUTPUT_DIR, _safe_slug
from multi_agentic_rag.utils.paths import ensure_runtime_dirs, resolve_path


@dataclass(frozen=True)
class CleanupResult:
    """Result of deleting one system's local runtime state."""

    system_name: str
    sqlite_deleted: dict[str, int] = field(default_factory=dict)
    chroma_deleted: int | None = None
    neo4j_deleted: int | None = None
    files_deleted: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def clean_system_state(
    system_name: str,
    *,
    settings: Settings | None = None,
    include_neo4j: bool = True,
    include_generated: bool = True,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> CleanupResult:
    """Remove one system from local runtime stores without touching other systems."""

    settings = settings or get_settings()
    registry = SQLiteRegistry(settings.sqlite_db_path)
    registry.initialize()
    runtime_paths = ensure_runtime_dirs(settings)
    sqlite_deleted, managed_files = _delete_sqlite_system(settings, system_name)

    warnings: list[str] = []
    chroma_deleted: int | None = None
    try:
        selection = select_vector_store(settings)
        delete_system = getattr(selection.store, "delete_system", None)
        if callable(delete_system):
            chroma_deleted = delete_system(system_name)
    except Exception as exc:
        warnings.append(f"Chroma/vector cleanup skipped: {exc}")

    neo4j_deleted: int | None = None
    if include_neo4j:
        graph_store = Neo4jGraphStore(settings)
        try:
            neo4j_deleted = graph_store.delete_system(system_name)
        except Exception as exc:
            warnings.append(f"Neo4j cleanup skipped: {exc}")
        finally:
            graph_store.close()

    files_deleted: list[str] = []
    for file_path in managed_files:
        if _delete_file_if_managed(file_path, runtime_paths["home"], runtime_paths["objects"]):
            files_deleted.append(str(file_path))

    if include_generated:
        generated_dir = resolve_path(output_dir) / _safe_slug(system_name)
        if _delete_directory_if_managed(generated_dir, resolve_path(output_dir)):
            files_deleted.append(str(generated_dir))

    return CleanupResult(
        system_name=system_name,
        sqlite_deleted=sqlite_deleted,
        chroma_deleted=chroma_deleted,
        neo4j_deleted=neo4j_deleted,
        files_deleted=files_deleted,
        warnings=warnings,
    )


def _delete_sqlite_system(settings: Settings, system_name: str) -> tuple[dict[str, int], list[Path]]:
    db_path = resolve_path(settings.sqlite_db_path)
    managed_files: list[Path] = []
    counts: dict[str, int] = {}
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        documents = connection.execute(
            "SELECT document_id, source_path FROM documents WHERE system_name = ?",
            (system_name,),
        ).fetchall()
        document_ids = [row["document_id"] for row in documents]
        for row in documents:
            if row["source_path"]:
                managed_files.append(resolve_path(row["source_path"]))
            managed_files.append(
                resolve_path(settings.object_store_path)
                / "parsed"
                / f"{row['document_id']}.chunks.jsonl"
            )

        coverage_ids = _coverage_ids_for_documents(connection, document_ids)
        tables = (
            ("test_run_results", "system_name = ?", [system_name]),
            ("generated_test_files", "system_name = ?", [system_name]),
            ("coverage_runs", "system_name = ?", [system_name]),
            ("coverage", _in_clause("coverage_id", coverage_ids), coverage_ids),
            ("deltas", "system_name = ?", [system_name]),
            ("facts", "system_name = ?", [system_name]),
            ("chunk_fts", "system_name = ?", [system_name]),
            ("chunks", "system_name = ?", [system_name]),
            ("documents", "system_name = ?", [system_name]),
        )
        for table, where_clause, params in tables:
            if not params and " IN " in where_clause:
                counts[table] = 0
                continue
            counts[table] = _count(connection, table, where_clause, params)
            connection.execute(f"DELETE FROM {table} WHERE {where_clause}", params)
    return counts, managed_files


def _coverage_ids_for_documents(connection: sqlite3.Connection, document_ids: list[str]) -> list[str]:
    where_clause = _in_clause("document_id", document_ids)
    if not document_ids:
        return []
    rows = connection.execute(
        f"SELECT coverage_id FROM coverage WHERE {where_clause}",
        document_ids,
    ).fetchall()
    return [str(row["coverage_id"]) for row in rows]


def _count(
    connection: sqlite3.Connection,
    table: str,
    where_clause: str,
    params: list[Any],
) -> int:
    row = connection.execute(
        f"SELECT count(*) AS count FROM {table} WHERE {where_clause}",
        params,
    ).fetchone()
    return int(row["count"] if row else 0)


def _in_clause(column_name: str, values: list[str]) -> str:
    if not values:
        return f"{column_name} IN (NULL)"
    placeholders = ", ".join("?" for _ in values)
    return f"{column_name} IN ({placeholders})"


def _delete_file_if_managed(path: Path, runtime_home: Path, object_root: Path) -> bool:
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_file():
        return False
    if not (resolved.is_relative_to(runtime_home) or resolved.is_relative_to(object_root)):
        return False
    resolved.unlink()
    return True


def _delete_directory_if_managed(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    resolved_root = root.resolve()
    if not resolved.exists() or not resolved.is_dir():
        return False
    if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
        return False
    shutil.rmtree(resolved)
    return True
