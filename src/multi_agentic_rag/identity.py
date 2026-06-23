"""Canonical deterministic identity helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_text(text: str) -> str:
    """Return the SHA-256 hex digest for text."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 hex digest for a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    """Hash Python data deterministically using JSON serialization."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_text(payload)


def stable_id(prefix: str, *parts: Any, length: int = 32) -> str:
    """Create a readable stable ID from typed parts."""

    digest = stable_hash(parts)[:length]
    return f"{prefix}_{digest}"
