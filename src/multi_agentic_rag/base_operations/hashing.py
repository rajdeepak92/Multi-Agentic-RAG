"""Deterministic hashing helpers."""

from __future__ import annotations

from pathlib import Path

from multi_agentic_rag.utils.hashing import sha256_file


def sha256_path(path: str | Path) -> str:
    """Return the SHA-256 hex digest for a local file."""

    return sha256_file(Path(path))
